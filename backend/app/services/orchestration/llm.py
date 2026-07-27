"""LLM engine (architecture 2: primary LLM = Claude via the Anthropic API).

Two interchangeable engines behind one interface:

  * AnthropicEngine — real Claude calls with a proper agentic tool loop
    (the model decides what analysis code to run, architecture 3 step 4).
  * OfflineEngine  — a deterministic, dependency-free engine used when no API key
    / SDK is present, so the product runs end-to-end for local development and CI.
    It is not a mock of the API; it is a real (simpler) reasoning path that still
    grounds on retrieved passages and still drives the sandbox for data questions.

The active engine is chosen at startup and exposed via get_engine().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ...config import settings

ToolExecutor = Callable[[str, dict], dict]


@dataclass
class TurnResult:
    text: str
    tool_events: list[dict] = field(default_factory=list)
    tier_used: str = "offline"


# --------------------------------------------------------------------------- #
#  Ollama engine (fully-local LLM — no API key)                               #
# --------------------------------------------------------------------------- #
class OllamaEngine:
    """Talks to a local Ollama server (http://localhost:11434) via its native
    /api/chat endpoint, including the tool-calling loop so the model can drive the
    analysis sandbox exactly like the Anthropic path.

    Requires a tool-capable model (e.g. llama3.1, qwen2.5, mistral-nemo) pulled
    into Ollama. Reachability is probed by get_engine() before this is selected.
    """

    available = True
    name = "ollama"

    def __init__(self, client=None) -> None:
        import httpx  # dependency already present
        from ...runtime import ollama_host
        self._httpx = httpx
        self._client = client or httpx.Client(
            base_url=ollama_host().rstrip("/"),
            timeout=settings.ollama_request_timeout,
            # Non-browser UA + skip header so an ngrok-tunnelled Ollama returns
            # JSON directly instead of ngrok's HTML interstitial. Harmless headers
            # for a direct Ollama server.
            headers={"ngrok-skip-browser-warning": "true", "User-Agent": "weave/1.0"},
        )

    def list_models(self) -> list[str]:
        """Names of models available on the Ollama server (for the model picker)."""
        try:
            r = self._client.get("/api/tags", timeout=10.0)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return sorted(n for n in models if n)
        except Exception:  # noqa: BLE001
            return []

    def model_context(self, name: str) -> int | None:
        """The model's trained context window, from Ollama's /api/show.

        Ollama reports it under `model_info` as "<architecture>.context_length"
        (e.g. "llama.context_length"), so the key is discovered by suffix rather
        than hard-coded per family. Results are memoised — /api/show is not
        cheap and the answer cannot change while the server is up.
        """
        cache = getattr(self, "_ctx_cache", None)
        if cache is None:
            cache = self._ctx_cache = {}
        if name in cache:
            return cache[name]
        ctx: int | None = None
        try:
            r = self._client.post("/api/show", json={"model": name}, timeout=15.0)
            r.raise_for_status()
            info = r.json().get("model_info") or {}
            for k, v in info.items():
                if k.endswith(".context_length") and isinstance(v, int):
                    ctx = v
                    break
        except Exception:  # noqa: BLE001 - a missing window is not an error
            ctx = None
        cache[name] = ctx
        return ctx

    def effective_context(self, name: str) -> int:
        """What the model will ACTUALLY see this turn.

        This is the single source of truth for both the request we send and the
        number the UI meter is drawn against — if they ever diverge the meter
        lies, which is worse than having no meter.

        The window follows the MODEL, bounded by a configured ceiling. An
        earlier version clamped to `ollama_num_ctx` unconditionally, which meant
        a 262k-token model was requested (and reported) at 8k. `ollama_num_ctx`
        is now only the fallback for a model whose window we cannot read.
        """
        trained = self.model_context(name)
        if trained:
            ceiling = settings.ollama_max_num_ctx or trained
            return max(1, min(trained, ceiling))
        return settings.ollama_num_ctx

    def ping(self) -> bool:
        # Tolerant of cold starts: a remote / ngrok-tunnelled Ollama's first
        # request can take several seconds before it warms up, so we allow a
        # generous timeout and fall back to /api/version as a liveness probe.
        for path in ("/api/version", "/api/tags"):
            try:
                r = self._client.get(path, timeout=12.0)
                if r.status_code == 200:
                    return True
            except Exception:  # noqa: BLE001 - try the next probe / give up
                continue
        return False

    def model_for_tier(self, tier: str) -> str:
        from ...runtime import ollama_model
        if tier == "frontier":
            return settings.ollama_model_frontier or ollama_model()
        return settings.ollama_model_fast or ollama_model()

    def _post_chat(self, payload: dict, attempts: int = 3):
        """POST /api/chat with retries on transient errors. A remote/ngrok-tunnelled
        Ollama occasionally drops a connection ('Server disconnected without sending
        a response') or times out on a cold call; one dropped packet should not fail
        the user's whole turn."""
        httpx = self._httpx
        transient = (
            httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError,
            httpx.ConnectTimeout, httpx.ReadError, httpx.PoolTimeout,
        )
        last_exc: Exception | None = None
        for i in range(attempts):
            try:
                resp = self._client.post("/api/chat", json=payload)
                resp.raise_for_status()
                return resp
            except transient as exc:  # noqa: PERF203 - retry loop
                last_exc = exc
                continue
            except httpx.HTTPStatusError as exc:
                # 5xx from the model server is also worth one retry
                if exc.response is not None and exc.response.status_code >= 500 and i < attempts - 1:
                    last_exc = exc
                    continue
                raise
        raise last_exc if last_exc else RuntimeError("ollama request failed")

    @staticmethod
    def _to_ollama_tools(tools: list[dict]) -> list[dict]:
        """Convert the Anthropic-style tool schema to Ollama's OpenAI-style one."""
        out = []
        for t in tools or []:
            out.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return out

    def generate(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_executor: ToolExecutor,
        tier: str,
        max_iters: int | None = None,
        on_event=None,          # live streaming callback: on_event(kind, data)
        model: str | None = None,
        effort: str | None = None,
        cancel=None,            # threading.Event: stop promptly on client disconnect
    ) -> TurnResult:
        """Agentic tool loop with TRUE token streaming.

        Uses Ollama's native streaming (stream:true, NDJSON). Each content delta is
        emitted immediately via on_event("token", ...) so the UI renders it as it is
        produced — no long idle gap that would otherwise idle-close the SSE socket.
        Supports the `think` parameter (streamed via on_event("thinking", ...)) and
        effort-tuned num_predict.
        """
        import json
        from ...runtime import effort_spec
        max_iters = max_iters or settings.llm_max_tool_iters
        model = model or self.model_for_tier(tier)
        spec = effort_spec(effort)
        ollama_tools = self._to_ollama_tools(tools)
        convo: list[dict[str, Any]] = [{"role": "system", "content": system}, *messages]
        tool_events: list[dict] = []
        final_text = ""

        def _cancelled() -> bool:
            return cancel is not None and cancel.is_set()

        for _ in range(max_iters):
            if _cancelled():
                return TurnResult(text=final_text.strip(), tool_events=tool_events, tier_used=tier)
            payload = {
                "model": model,
                "messages": convo,
                "tools": ollama_tools,
                "stream": True,
                "options": {
                    # Same resolution the UI meter is drawn against, so the
                    # gauge always reflects the window actually requested.
                    "num_ctx": self.effective_context(model),
                    "temperature": 0.4,
                    "num_predict": spec["num_predict"],
                },
            }
            if spec.get("think"):
                payload["think"] = True

            content_parts: list[str] = []
            tool_calls: list[dict] = []
            try:
                with self._client.stream("POST", "/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if _cancelled():
                            break
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        m = obj.get("message", {}) or {}
                        thinking = m.get("thinking")
                        if thinking and on_event:
                            on_event("thinking", {"text": thinking})
                        delta = m.get("content", "") or ""
                        if delta:
                            content_parts.append(delta)
                            if on_event:
                                on_event("token", {"text": delta})
                        if m.get("tool_calls"):
                            tool_calls.extend(m["tool_calls"])
                        if obj.get("done"):
                            break
            except Exception:  # noqa: BLE001 - fall back to non-streaming for this step
                resp2 = self._post_chat({**payload, "stream": False})
                m = resp2.json().get("message", {}) or {}
                text = m.get("content", "") or ""
                if text and on_event:
                    on_event("token", {"text": text})
                content_parts = [text]
                tool_calls = m.get("tool_calls") or []

            step_text = "".join(content_parts)
            convo.append({
                "role": "assistant", "content": step_text,
                **({"tool_calls": tool_calls} if tool_calls else {}),
            })

            if not tool_calls:
                final_text = step_text
                return TurnResult(text=final_text.strip(), tool_events=tool_events, tier_used=tier)

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                result = tool_executor(name, args)
                tool_events.append({"name": name, "input": args, "result": result})
                convo.append({"role": "tool", "tool_name": name, "content": _stringify_tool_result(result)})

        return TurnResult(
            text=final_text or "(reached the tool-iteration limit).",
            tool_events=tool_events, tier_used=tier,
        )

    def translate(self, text: str, target_language: str) -> str:
        lang = "Kiswahili" if target_language == "sw" else "English"
        resp = self._post_chat({
            "model": self.model_for_tier("fast"),
            "messages": [
                {"role": "system",
                 "content": f"Translate the user's message into academic {lang}. "
                            "Output only the translation, nothing else."},
                {"role": "user", "content": text},
            ],
            "stream": False,
        })
        return (resp.json().get("message", {}).get("content") or "").strip()


# --------------------------------------------------------------------------- #
#  Anthropic engine                                                           #
# --------------------------------------------------------------------------- #
class AnthropicEngine:
    available = True
    name = "anthropic"

    def __init__(self) -> None:
        from anthropic import Anthropic  # imported lazily; may raise ImportError
        self._client = Anthropic(api_key=settings.anthropic_api_key)

    def model_for_tier(self, tier: str) -> str:
        return settings.model_tier_frontier if tier == "frontier" else settings.model_tier_fast

    def generate(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_executor: ToolExecutor,
        tier: str,
        max_iters: int | None = None,
        on_event=None, model: str | None = None, effort: str | None = None, cancel=None,
    ) -> TurnResult:
        max_iters = max_iters or settings.llm_max_tool_iters
        model = model or self.model_for_tier(tier)
        convo = list(messages)
        tool_events: list[dict] = []

        for _ in range(max_iters):
            resp = self._client.messages.create(
                model=model,
                max_tokens=settings.llm_max_tokens,
                system=system,
                tools=tools or [],
                messages=convo,
            )
            # collect assistant content
            assistant_content = [self._block_to_dict(b) for b in resp.content]
            convo.append({"role": "assistant", "content": assistant_content})

            if resp.stop_reason != "tool_use":
                text = "".join(b.text for b in resp.content if b.type == "text")
                return TurnResult(text=text.strip(), tool_events=tool_events, tier_used=tier)

            # execute each requested tool, feed results back
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                result = tool_executor(block.name, dict(block.input))
                tool_events.append({"name": block.name, "input": dict(block.input), "result": result})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _stringify_tool_result(result),
                })
            convo.append({"role": "user", "content": tool_results})

        return TurnResult(
            text="(The assistant reached the tool-iteration limit before finishing.)",
            tool_events=tool_events, tier_used=tier,
        )

    def translate(self, text: str, target_language: str) -> str:
        lang = "Kiswahili" if target_language == "sw" else "English"
        resp = self._client.messages.create(
            model=settings.model_tier_fast,
            max_tokens=settings.llm_max_tokens,
            system=f"Translate the user's message into academic {lang}. Output only the translation.",
            messages=[{"role": "user", "content": text}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    @staticmethod
    def _block_to_dict(block: Any) -> dict:
        if block.type == "text":
            return {"type": "text", "text": block.text}
        if block.type == "tool_use":
            return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
        return {"type": block.type}


def _stringify_tool_result(result: dict) -> str:
    import json
    return json.dumps(result, ensure_ascii=False)[:8000]


# --------------------------------------------------------------------------- #
#  Offline engine                                                             #
# --------------------------------------------------------------------------- #
class OfflineEngine:
    available = False
    name = "offline"

    def model_for_tier(self, tier: str) -> str:
        return "offline-deterministic"

    def compose(
        self,
        *,
        language: str,
        mode: str,
        intent: str,
        user_text: str,
        passages: list[dict],
        analysis: dict | None,
        integrity_triggered: bool,
    ) -> str:
        sw = language == "sw"
        parts: list[str] = []

        if integrity_triggered:
            if sw:
                parts.append(
                    "Siwezi kuandika kazi yako badala yako, lakini nitakusaidia uiandike mwenyewe. "
                    "Tuanze na muundo: hoja yako kuu ni ipi, na utaithibitisha kwa vipengele vipi vitatu?"
                )
            else:
                parts.append(
                    "I won't write the assignment for you, but I'll help you write it yourself. "
                    "Let's start with an outline: what is your main claim, and what three points "
                    "will support it?"
                )

        if analysis is not None:
            parts.append(self._describe_analysis(analysis, sw))

        if passages:
            if sw:
                parts.append("Kwa mujibu wa vyanzo vilivyopatikana:")
            else:
                parts.append("Based on the retrieved sources:")
            for i, p in enumerate(passages[:3], start=1):
                access = p.get("access_status", "open")
                snippet = p.get("content", "")[:220].strip()
                tag = "(inayolipiwa)" if access == "paywalled" and sw else (
                    "(paywalled)" if access == "paywalled" else "")
                parts.append(f"[S{i}] {p.get('title')} {tag}\n{snippet}…")
            if sw:
                parts.append(
                    "Kumbuka kuangalia hali ya upatikanaji (wazi/inayolipiwa) kabla ya kutumia chanzo."
                )
        elif not analysis and not integrity_triggered:
            if intent in {"literature", "concept"}:
                if sw:
                    parts.append(
                        "Sina chanzo cha ndani kilichopatikana kwa swali hili, hivyo sitatoa takwimu "
                        "au sheria mahususi kama ukweli uliothibitishwa. Naweza kukueleza dhana kwa "
                        "ujumla, au tuboreshe swali liwe mahususi zaidi."
                    )
                else:
                    parts.append(
                        "I have no grounded local source for this question, so I won't state specific "
                        "statistics or laws as established fact. I can explain the concept generally, "
                        "or we can narrow the question."
                    )
            else:
                parts.append(self._generic_help(user_text, sw, mode))

        if mode == "student" and not integrity_triggered:
            parts.append(
                "Je, hii iko wazi kabla hatujaenda hatua inayofuata?" if sw
                else "Does that make sense before we go to the next step?"
            )
        return "\n\n".join(p for p in parts if p).strip()

    def translate(self, text: str, target_language: str) -> str:
        # No translation service offline. Return the text with an honest marker so
        # the bilingual toggle still shows content rather than a blank field.
        note = "[Tafsiri ya moja kwa moja haipatikani nje ya mtandao]" if target_language == "sw" \
            else "[Automatic translation unavailable offline]"
        return f"{note}\n\n{text}"

    def _describe_analysis(self, analysis: dict, sw: bool) -> str:
        status = analysis.get("status")
        if status == "rejected":
            return ("Msimbo wa uchambuzi ulikataliwa na ukaguzi wa usalama." if sw
                    else "The analysis code was rejected by the sandbox safety check.")
        if status == "timeout":
            return ("Uchambuzi ulizidi muda ulioruhusiwa." if sw
                    else "The analysis exceeded the allowed time limit.")
        if status != "ok":
            return ("Uchambuzi ulikumbwa na hitilafu:\n" if sw
                    else "The analysis hit an error:\n") + (analysis.get("stderr", "")[:500])
        out = analysis.get("stdout", "").strip()
        files = analysis.get("output_files", [])
        head = ("Nimeuendesha uchambuzi kwenye data yako. Matokeo:" if sw
                else "I ran the analysis on your data. Results:")
        body = f"\n```\n{out[:1500]}\n```" if out else ""
        charts = ""
        if files:
            names = ", ".join(f.get("name", "") for f in files)
            charts = (f"\nChati/majedwali yaliyotengenezwa: {names}" if sw
                      else f"\nGenerated charts/tables: {names}")
        return head + body + charts

    def _generic_help(self, user_text: str, sw: bool, mode: str) -> str:
        if sw:
            return (
                "Nipo hapa kukusaidia na masomo na utafiti kwa Kiswahili na Kiingereza. "
                "Unaweza kuniuliza dhana, kupakia data kwa uchambuzi, au kutafuta vyanzo vya Kitanzania."
            )
        return (
            "I'm here to help with study and research in Kiswahili and English. "
            "You can ask about a concept, upload data for analysis, or search Tanzanian sources."
        )


# --------------------------------------------------------------------------- #
_Engine = OllamaEngine | AnthropicEngine | OfflineEngine
_engine: _Engine | None = None


def _try_ollama() -> OllamaEngine | None:
    try:
        eng = OllamaEngine()
        return eng if eng.ping() else None
    except Exception:  # noqa: BLE001 - httpx missing / unreachable
        return None


def _try_anthropic() -> AnthropicEngine | None:
    if not settings.anthropic_api_key:
        return None
    try:
        return AnthropicEngine()
    except Exception:  # noqa: BLE001 - SDK missing / init failed
        return None


def get_engine() -> _Engine:
    """Select the active LLM engine per WEAVE_LLM_BACKEND.

    auto (default): Ollama if a local server is reachable, else Anthropic if a key
    is configured, else the deterministic offline engine. Every branch degrades to
    offline so the platform always boots.
    """
    global _engine
    if _engine is not None:
        return _engine

    if settings.force_offline_llm:
        _engine = OfflineEngine()
        return _engine

    backend = (settings.llm_backend or "auto").lower()
    if backend == "offline":
        _engine = OfflineEngine()
    elif backend == "ollama":
        _engine = _try_ollama() or OfflineEngine()
    elif backend == "anthropic":
        _engine = _try_anthropic() or OfflineEngine()
    else:  # auto
        _engine = _try_ollama() or _try_anthropic() or OfflineEngine()
    return _engine


def reset_engine() -> None:
    """Test hook."""
    global _engine
    _engine = None
