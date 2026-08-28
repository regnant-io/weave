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

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ...config import settings

log = logging.getLogger("weave.llm")

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

    #: How long a /api/tags listing stays fresh. Long enough that a turn does not
    #: pay for it repeatedly, short enough that pulling a new model shows up
    #: without a restart.
    _TAGS_TTL = 60.0

    def tags(self, *, force: bool = False) -> list[dict]:
        """The raw model listing from Ollama, memoised briefly.

        Kept as the full records rather than just names because the fields that
        matter most for routing — `capabilities` (does it support tools at all?)
        and `details.parameter_size` — are only here. Deciding those from the
        model NAME, which is what this code used to do, is guesswork that gets
        `minimax-m3:cloud` and `gemma4:cloud` wrong.
        """
        import time

        cached = getattr(self, "_tags_cache", None)
        if cached and not force and (time.monotonic() - cached[0]) < self._TAGS_TTL:
            return cached[1]
        try:
            r = self._client.get("/api/tags", timeout=10.0)
            r.raise_for_status()
            models = [m for m in (r.json().get("models") or []) if m.get("name")]
        except Exception:  # noqa: BLE001 - unreachable server: report nothing
            models = cached[1] if cached else []
        self._tags_cache = (time.monotonic(), models)
        return models

    def list_models(self) -> list[str]:
        """Names of models available on the Ollama server (for the model picker)."""
        return sorted(m["name"] for m in self.tags())

    def capabilities(self, name: str) -> set[str]:
        """What the server says this model can do ('tools', 'thinking', 'vision')."""
        for m in self.tags():
            if m.get("name") == name:
                return {str(c) for c in (m.get("capabilities") or [])}
        return set()

    def parameter_billions(self, name: str) -> float:
        """Parameter count in billions, or 0.0 when the server does not say.

        Hosted `:cloud` models report "0" for some entries, which is why this is
        only ever one input to `model_class` and never the deciding one.
        """
        for m in self.tags():
            if m.get("name") != name:
                continue
            raw = str((m.get("details") or {}).get("parameter_size") or "").strip().upper()
            try:
                if raw.endswith("B"):
                    return float(raw[:-1])
                if raw.endswith("M"):
                    return float(raw[:-1]) / 1000.0
                return float(raw)
            except ValueError:
                return 0.0
        return 0.0

    def supports_tools(self, name: str) -> bool:
        """Whether this model can drive the orchestrator at all.

        A model with no tool support cannot run analysis, cannot search, cannot
        render — it can only talk. Selecting one silently turns Weave back into
        a chat window, so it is filtered out of automatic selection (a user who
        explicitly picks one still gets it).
        """
        caps = self.capabilities(name)
        # An older Ollama omits the field entirely; absence is not evidence of
        # absence, so an unannotated model stays eligible.
        return "tools" in caps if caps else True

    def model_class(self, name: str) -> str:
        """"large" or "small" — how much prompt guidance is worth its tokens.

        Judged from what the SERVER reports, not from the model's name:

          * a model advertising `thinking` is a reasoning model by construction,
            whatever it is called;
          * 27B+ parameters is large;
          * a hosted `:cloud` tag is a frontier-class endpoint even when the
            parameter count comes back as 0, which is exactly the case that made
            the old name-regex classify `minimax-m3:cloud` as a small local
            model and hand it the cut-down prompt.
        """
        caps = self.capabilities(name)
        if "thinking" in caps:
            return "large"
        if self.parameter_billions(name) >= 27:
            return "large"
        if name.endswith(":cloud") or ":cloud-" in name:
            return "large"
        return "small"

    def resolve_model(self, requested: str | None = None) -> str:
        """A model that actually EXISTS on this server and can use tools.

        The configured default is a string in a `.env` file, and it drifts: the
        shipped default was `llama3.2:3b` on a server that had never pulled it.
        Every turn then made three retried calls to a 404, gave up, and fell
        back to the deterministic offline engine — so the product answered every
        question with its no-LLM fallback path while reporting `llm_engine:
        "ollama"` as healthy. Nothing surfaced the mismatch.

        So: honour what is asked for when it is really there, and otherwise pick
        the best thing that is, loudly.
        """
        names = {m["name"] for m in self.tags()}
        if requested and requested in names:
            return requested
        # Ollama accepts an implicit ':latest'; treat that as a match.
        if requested and f"{requested}:latest" in names:
            return f"{requested}:latest"

        usable = [n for n in sorted(names) if self.supports_tools(n)]
        if not usable:
            # Nothing tool-capable. Returning the request unchanged keeps the
            # failure honest rather than substituting a model that cannot work.
            return requested or settings.ollama_model

        def rank(n: str) -> tuple:
            """Preference order, most significant first.

            Reasoning capability outranks raw size because this orchestrator
            plans, critiques and repairs its own work — a model that cannot
            think through a multi-step plan is the wrong instrument however
            many parameters it has. Size then decides among reasoning models,
            and vision and context window break the remaining ties (vision
            matters for screen sharing and for critiquing a rendered artifact).
            """
            caps = self.capabilities(n)
            try:
                ctx = self.effective_context(n)
            except Exception:  # noqa: BLE001
                ctx = 0
            return (
                self.model_class(n) == "large",
                "thinking" in caps,
                self.parameter_billions(n),
                "vision" in caps,
                ctx,
                n,
            )

        best = max(usable, key=rank)
        if requested:
            log.warning(
                "configured Ollama model %r is not present on %s; using %r instead. "
                "Pull it, or set WEAVE_OLLAMA_MODEL to one of: %s",
                # Defensive: this is the diagnostic for a misconfiguration, and
                # it must not itself be able to raise on the way out.
                requested, getattr(self._client, "base_url", "the configured host"),
                best, ", ".join(usable[:8]),
            )
        return best

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

        The window follows the MODEL. `ollama_num_ctx` is only the fallback for
        a model whose window we cannot read, and `ollama_max_num_ctx` is an
        OPT-IN ceiling (0 = none). Both of those used to clamp unconditionally,
        which is what capped every model at 32k and truncated long generations.
        """
        trained = self.model_context(name)
        if trained:
            ceiling = settings.ollama_max_num_ctx
            ctx = min(trained, ceiling) if ceiling and ceiling > 0 else trained
        else:
            ctx = settings.ollama_num_ctx
        return max(settings.ollama_min_num_ctx, int(ctx))

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
        configured = (
            settings.ollama_model_frontier if tier == "frontier" else settings.ollama_model_fast
        ) or ollama_model()
        return self.resolve_model(configured)

    #: How long to wait before retrying a rate-limited request, per attempt.
    #: Hosted models (`:cloud`) are metered, and an agentic turn makes many calls
    #: in quick succession — planning, several tool rounds, a review — so 429 is
    #: a NORMAL condition here, not an error. It used to abort the turn and drop
    #: silently to the offline engine, which produced a visibly worse answer with
    #: nothing anywhere saying why.
    _BACKOFF = (2.0, 5.0, 12.0, 25.0)

    def _sleep_for_retry(self, response, attempt: int, on_event=None) -> float:
        """Honour Retry-After when the server sends one, else back off."""
        wait = self._BACKOFF[min(attempt, len(self._BACKOFF) - 1)]
        try:
            header = (response.headers or {}).get("retry-after") if response is not None else None
            if header:
                wait = max(wait, min(float(header), 60.0))
        except (TypeError, ValueError):
            pass
        if on_event:
            # Say it out loud. A thirty-second pause with no explanation is
            # indistinguishable from a hang.
            on_event("notice", {
                "kind": "rate_limited",
                "text": f"The model provider is rate-limiting; retrying in {int(wait)}s.",
                "seconds": int(wait),
            })
        return wait

    def _post_chat(self, payload: dict, attempts: int = 4, on_event=None):
        """POST /api/chat with retries on transient errors and on rate limits.

        A remote/ngrok-tunnelled Ollama occasionally drops a connection ('Server
        disconnected without sending a response') or times out on a cold call;
        one dropped packet should not fail the user's whole turn. A hosted model
        returns 429 under load, which is a wait, not a failure.
        """
        import time as _time

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
                status = exc.response.status_code if exc.response is not None else 0
                if i >= attempts - 1:
                    raise
                if status == 429:
                    _time.sleep(self._sleep_for_retry(exc.response, i, on_event))
                    last_exc = exc
                    continue
                if status >= 500:
                    last_exc = exc
                    continue
                raise
        raise last_exc if last_exc else RuntimeError("ollama request failed")

    def _await_capacity(self, payload: dict, on_event=None, attempts: int = 4) -> None:
        """Block until the provider will accept a streaming request.

        Streaming cannot retry mid-flight — once tokens have been emitted to the
        client, replaying the call would duplicate them on screen. So the rate
        limit is absorbed here, before anything is streamed, by opening the
        stream and immediately closing it if the status is 429.
        """
        import time as _time

        httpx = self._httpx
        for i in range(attempts):
            try:
                with self._client.stream("POST", "/api/chat",
                                         json={**payload, "stream": True}) as probe:
                    if probe.status_code != 429:
                        return
                    response = probe
                    probe.read()
            except httpx.HTTPStatusError as exc:
                if exc.response is None or exc.response.status_code != 429:
                    return
                response = exc.response
            except Exception:  # noqa: BLE001 - a connection problem is the caller's to handle
                return
            if i >= attempts - 1:
                return
            _time.sleep(self._sleep_for_retry(response, i, on_event))

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
        from ...runtime import effort_spec, num_predict_for
        max_iters = max_iters or settings.llm_max_tool_iters
        # Resolve even an explicit choice: a model the user picked before it was
        # removed from the server would otherwise 404 three times and silently
        # degrade the whole turn to the offline engine.
        model = self.resolve_model(model) if model else self.model_for_tier(tier)
        spec = effort_spec(effort)
        # Resolved ONCE per turn: /api/show is memoised but the value is used on
        # every tool iteration, and the meter must be drawn against this exact
        # number.
        num_ctx = self.effective_context(model)
        num_predict = num_predict_for(effort, num_ctx)
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
                    "num_ctx": num_ctx,
                    "temperature": 0.4,
                    # -1 = let the model run to its natural stop. A fixed ceiling
                    # here is what used to cut long files off mid-line.
                    "num_predict": num_predict,
                },
            }
            if spec.get("think"):
                payload["think"] = True

            content_parts: list[str] = []
            tool_calls: list[dict] = []
            try:
                # A rate limit has to be waited out BEFORE the stream opens.
                # Without this the streaming path had no retry at all: the 429
                # raised, the except below fell through to the non-streaming
                # call, that raised 429 too, and the whole turn degraded to the
                # offline engine with nothing telling the user why the answer
                # suddenly got worse.
                self._await_capacity(payload, on_event)
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
                resp2 = self._post_chat({**payload, "stream": False}, on_event=on_event)
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

    @staticmethod
    def _with_images(message: dict[str, Any]) -> dict[str, Any]:
        """Translate Weave's engine-neutral `images` key into Anthropic blocks.

        Screen sharing attaches base64 JPEG frames to the user's turn as
        `{"role": "user", "content": "...", "images": [b64, ...]}`. Ollama
        consumes exactly that shape natively, so it is the format the
        orchestrator produces; Anthropic wants typed content blocks instead.
        Converting here keeps the orchestrator free of per-vendor branching, and
        a message with no images passes through untouched.
        """
        images = message.get("images")
        if not images:
            return message
        blocks: list[dict[str, Any]] = []
        content = message.get("content")
        if isinstance(content, str) and content:
            blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            blocks.extend(content)
        for data in images:
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": data},
            })
        out = {k: v for k, v in message.items() if k != "images"}
        out["content"] = blocks
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
        on_event=None, model: str | None = None, effort: str | None = None, cancel=None,
    ) -> TurnResult:
        max_iters = max_iters or settings.llm_max_tool_iters
        model = model or self.model_for_tier(tier)
        convo = [self._with_images(m) for m in messages]
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
            # A retrieval miss is not a refusal.
            #
            # This branch used to end the answer with "I won't state specific
            # statistics… or we can narrow the question" — the same defensive
            # posture that was removed from the system prompt, hardcoded here
            # where no prompt change can reach it. Since the offline engine is
            # what runs when there is no Ollama and no API key, that made the
            # DEFAULT experience of Weave a decline.
            #
            # Now it says what is actually true — nothing was retrieved, so
            # specifics need checking — and then gets on with helping.
            if intent in {"literature", "concept"}:
                if sw:
                    parts.append(
                        "Sikupata chanzo cha ndani kwa swali hili, hivyo takwimu au sheria "
                        "mahususi zinahitaji kuhakikiwa kabla ya kuzitegemea. Hebu tuanze na "
                        "dhana yenyewe:"
                    )
                else:
                    parts.append(
                        "I did not retrieve a local source for this, so treat any specific "
                        "figure or legal provision below as needing a check. Here is the "
                        "concept itself:"
                    )
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
