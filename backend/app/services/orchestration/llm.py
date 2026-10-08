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
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from ...config import settings

log = logging.getLogger("weave.llm")

ToolExecutor = Callable[[str, dict], dict]


class QuotaExhausted(RuntimeError):
    """The provider will not serve this account until something changes.

    Distinct from a transport failure because the remedy is different and the
    user can act on it: upgrade the plan, wait for the window to reset, or pick
    a different model. Carrying the provider's own message means the answer they
    get names the account and the upgrade link rather than saying "unavailable".
    """


@dataclass
class TurnResult:
    text: str
    tool_events: list[dict] = field(default_factory=list)
    tier_used: str = "offline"


#: How many tool calls from one model turn may be in flight at once.
#:
#: Small on purpose. The point is to stop three web searches taking three times
#: as long as one, not to saturate the machine: every one of these holds a
#: worker thread, and with a thousand students on one instance the thread count
#: is the scarce resource, not the latency of any single call.
MAX_PARALLEL_TOOLS = 4


def _run_tool_calls(
    calls: list[tuple[str, dict]],
    tool_executor: ToolExecutor,
    parallel_safe: set[str] | None,
    *,
    cancel=None,
) -> list[tuple[str, dict, dict]]:
    """Execute one model turn's tool calls, concurrently when that is safe.

    Returns `(name, args, result)` IN THE ORDER THE MODEL ASKED FOR THEM,
    whatever order they actually completed in. That matters: the results go back
    into the conversation as messages, and a model that asked A-then-B and is
    answered B-then-A has been handed a transcript of a turn that did not
    happen.

    Concurrency is all-or-nothing per batch. A mixed batch runs serially rather
    than being split, because the interesting mixed case -- read a file, then
    write it -- is precisely the one where reordering is wrong, and the
    valuable case (several independent lookups at once) is homogeneous anyway.
    """
    if not calls:
        return []

    safe = parallel_safe or set()
    if len(calls) < 2 or not all(name in safe for name, _ in calls):
        out = []
        for name, args in calls:
            if cancel is not None and cancel.is_set():
                out.append((name, args, {
                    "status": "cancelled",
                    "error": "the user stopped this turn before this ran",
                }))
                continue
            out.append((name, args, tool_executor(name, args)))
        return out

    from concurrent.futures import ThreadPoolExecutor

    results: list[dict | None] = [None] * len(calls)

    def run(i: int) -> None:
        name, args = calls[i]
        if cancel is not None and cancel.is_set():
            results[i] = {"status": "cancelled",
                          "error": "the user stopped this turn before this ran"}
            return
        try:
            results[i] = tool_executor(name, args)
        except Exception as exc:  # noqa: BLE001 - a thread must not die silently
            log.warning("parallel tool %s failed: %s", name, exc)
            results[i] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    with ThreadPoolExecutor(
        max_workers=min(MAX_PARALLEL_TOOLS, len(calls)),
        thread_name_prefix="weave-tool",
    ) as pool:
        list(pool.map(run, range(len(calls))))

    return [(calls[i][0], calls[i][1], results[i] or {"status": "error", "error": "no result"})
            for i in range(len(calls))]


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
    #: Whether `generate` emits `token` events as the answer is produced.
    #: The orchestrator asks the ENGINE rather than comparing `name` against a
    #: hard-coded string -- which is how the Anthropic path kept re-emitting an
    #: answer it had already streamed for months after it learned to stream.
    streams = True

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

    def vision_model(self) -> str:
        """The best model here that can actually look at an image, or "".

        Separate from `resolve_model` because the two want different things: the
        model that writes a Babylon scene should be the strongest reasoner
        available, while the model that answers "is anything cut off in this
        picture" only has to have eyes. Asking a text-only model to review a
        screenshot returns a confident description of an image it never saw,
        which is worse than not asking.
        """
        candidates = [m["name"] for m in self.tags()
                      if "vision" in self.capabilities(m["name"])]
        if not candidates:
            return ""
        return max(candidates, key=lambda n: (self.supports_tools(n),
                                              self.parameter_billions(n), n))

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

    @staticmethod
    def _quota_message(response) -> str:
        """The provider's own words when a 429 means 'you are out', not 'slow down'.

        These are different conditions wearing the same status code, and telling
        them apart is worth real effort:

          * a BURST limit clears in seconds, so backing off is exactly right;
          * a SESSION or plan limit does not clear at all within the session, so
            backing off spends forty-five seconds to arrive at the same failure,
            and then degrades the answer without explaining why.

        Ollama Cloud says which it is in the body:
            "you (someone) have reached your session usage limit, upgrade for
             higher limits: https://ollama.com/upgrade"

        Returned verbatim when matched, because the provider's message names the
        account and the upgrade path, and anything we substitute would be vaguer.
        """
        try:
            body = response.text if response is not None else ""
        except Exception:  # noqa: BLE001
            return ""
        low = body.lower()
        if not any(marker in low for marker in
                   ("usage limit", "upgrade for higher", "quota", "insufficient credit",
                    "out of credits", "billing")):
            return ""
        try:
            import json as _json
            detail = str(_json.loads(body).get("error") or "").strip()
        except Exception:  # noqa: BLE001 - not JSON; use the raw text
            detail = body.strip()
        return detail[:400] or "the model provider reports the account is out of quota"

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
                    quota = self._quota_message(exc.response)
                    if quota:
                        raise QuotaExhausted(quota) from exc
                    _time.sleep(self._sleep_for_retry(exc.response, i, on_event))
                    last_exc = exc
                    continue
                if status >= 500:
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
        parallel_safe: set[str] | None = None,
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
        #: Every non-empty thing the model SAID this turn, in order.
        #:
        #: This used to be a single `final_text` assigned only on the step that
        #: emitted no tool calls. Models routinely write a paragraph and then
        #: call a tool -- "Here is what the survey found; let me chart it" --
        #: and that paragraph was streamed to the screen and then thrown away,
        #: because the turn's stored text was whatever the LAST step happened to
        #: say. The transcript was right until the page was reloaded, at which
        #: point half the answer had never been saved. Keeping every part means
        #: what is persisted is what the reader actually saw.
        said: list[str] = []
        cutoffs = 0

        def _cancelled() -> bool:
            return cancel is not None and cancel.is_set()

        for _ in range(max_iters):
            if _cancelled():
                # `said`, not the long-gone `final_text`: that name raised
                # NameError here, so every Stop or steer that landed between
                # steps crashed the turn into the offline fallback.
                return TurnResult(text="\n\n".join(said).strip(),
                                  tool_events=tool_events, tier_used=tier)
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
            done_reason = ""
            #: Characters actually pushed to the client for THIS step. Distinct
            #: from `content_parts`, which is what we will keep -- the two
            #: diverge exactly when a stream dies part-way and has to be
            #: re-issued, which is the case handled below.
            emitted = ""

            def _emit_token(text: str) -> None:
                nonlocal emitted
                if not text or on_event is None:
                    return
                emitted += text
                on_event("token", {"text": text})

            try:
                # Rate limits are handled INSIDE the streaming request, by
                # checking the status before consuming the body.
                #
                # httpx exposes the status as soon as the response head arrives,
                # so a 429 can be retried here with nothing yet on the user's
                # screen — which is the whole difficulty: once tokens have been
                # emitted, replaying the call would duplicate them.
                #
                # The previous attempt at this sent a separate probe request
                # first. That doubled every call to a metered endpoint, and the
                # probe consumed a generation that was then thrown away.
                for attempt in range(4):
                    with self._client.stream("POST", "/api/chat", json=payload) as resp:
                        if resp.status_code == 429:
                            resp.read()
                            quota = self._quota_message(resp)
                            if quota:
                                raise QuotaExhausted(quota)
                            if attempt < 3:
                                import time as _t
                                _t.sleep(self._sleep_for_retry(resp, attempt, on_event))
                                continue
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
                                _emit_token(delta)
                            if m.get("tool_calls"):
                                tool_calls.extend(m["tool_calls"])
                            if obj.get("done"):
                                done_reason = str(obj.get("done_reason") or "")
                                break
                    break
            except QuotaExhausted:
                raise
            except Exception:  # noqa: BLE001 - fall back to non-streaming for this step
                resp2 = self._post_chat({**payload, "stream": False}, on_event=on_event)
                body2 = resp2.json()
                done_reason = str(body2.get("done_reason") or "")
                m = body2.get("message", {}) or {}
                text = m.get("content", "") or ""
                tool_calls = m.get("tool_calls") or []
                content_parts = [text]
                if emitted:
                    # The stream died PART-WAY THROUGH. Whatever it managed to
                    # send is already on the user's screen, and the retry above
                    # generated the answer again from the beginning -- so
                    # emitting it wholesale printed the opening of the answer
                    # twice, interleaved with itself. That is the "overlapping
                    # tokens" fault, and it is invisible in the logs because
                    # both halves are individually correct.
                    if text.startswith(emitted):
                        # The regeneration agrees with what was shown. Send only
                        # what the reader has not seen.
                        _emit_token(text[len(emitted):])
                    else:
                        # It diverged. There is no way to splice two different
                        # continuations into one honest answer, so retract what
                        # was shown and replay the whole thing. `answer_restart`
                        # is the same event steering uses for exactly this.
                        if on_event:
                            on_event("answer_restart", {"reason": "stream_recovered"})
                        emitted = ""
                        _emit_token(text)
                else:
                    _emit_token(text)

            step_text = "".join(content_parts)
            if (done_reason == "length" and cutoffs < _MAX_CUTOFF_RECOVERIES
                    and not _cancelled()):
                # Cut off at num_predict. Whatever tool call was being written
                # is incomplete, so it is not executed; the model is told why
                # and continues, instead of the turn ending mid-sentence.
                cutoffs += 1
                if step_text.strip():
                    said.append(step_text.strip())
                convo.append({"role": "assistant", "content": step_text})
                convo.append({"role": "user", "content": _CUTOFF_NOTICE})
                continue
            convo.append({
                "role": "assistant", "content": step_text,
                **({"tool_calls": tool_calls} if tool_calls else {}),
            })

            if step_text.strip():
                said.append(step_text.strip())

            if not tool_calls or _cancelled():
                # A stream cut short by Stop can end holding a half-received
                # tool call. Executing it would act on an instruction the user
                # has just withdrawn.
                return TurnResult(text="\n\n".join(said).strip(),
                                  tool_events=tool_events, tier_used=tier)

            calls = []
            malformed: dict[int, dict] = {}
            for index, tc in enumerate(tool_calls):
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args, problem = _parse_tool_arguments(fn.get("arguments", {}))
                if problem:
                    # Executing with `{}` used to turn a truncated argument
                    # string into "x is required", which sent the model hunting
                    # for a missing field instead of re-sending valid JSON.
                    malformed[index] = {"status": "error", "code": "invalid_tool_arguments",
                                        "retryable": True, "error": problem}
                calls.append((name, args))

            runnable = [c for i, c in enumerate(calls) if i not in malformed]
            outcomes = iter(_run_tool_calls(runnable, tool_executor, parallel_safe, cancel=cancel))
            for index, (name, args) in enumerate(calls):
                result = malformed[index] if index in malformed else next(outcomes)[2]
                tool_events.append({"name": name, "input": args, "result": result})
                convo.append({"role": "tool", "tool_name": name,
                              "content": _stringify_tool_result(result)})

        said.append(
            "(I reached the limit on how many tool calls one turn may make, so this "
            "is as far as I got.)"
        )
        return TurnResult(
            text="\n\n".join(said).strip(),
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
    streams = True

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
        parallel_safe: set[str] | None = None,
    ) -> TurnResult:
        """Agentic tool loop, STREAMED.

        This path used to call `messages.create` and hand back the finished
        answer. Everything above it — the SSE route, the smoother, the whole
        transcript — is built to render text as it is produced, so on the
        Anthropic engine the user watched a blank turn for however long the
        model took and then received the entire answer in one frame. Worse, the
        orchestrator's `engine_streamed` flag is only set for Ollama, so the
        finished text was then re-emitted through a fake token generator: the
        product's own fallback for "this engine cannot stream" was hiding the
        fact that this engine can.

        It also ignored `cancel`, so pressing Stop released the client while the
        model kept generating and the tools kept running.
        """
        max_iters = max_iters or settings.llm_max_tool_iters
        model = model or self.model_for_tier(tier)
        convo = [self._with_images(m) for m in messages]
        tool_events: list[dict] = []
        said: list[str] = []
        cutoffs = 0

        def _cancelled() -> bool:
            return cancel is not None and cancel.is_set()

        for _ in range(max_iters):
            if _cancelled():
                break

            assistant_content: list[dict] = []
            step_text = ""
            stop_reason = "end_turn"

            with self._client.messages.stream(
                model=model,
                max_tokens=settings.llm_max_tokens,
                system=system,
                tools=tools or [],
                messages=convo,
            ) as stream:
                for chunk in stream.text_stream:
                    if _cancelled():
                        break
                    if chunk:
                        step_text += chunk
                        if on_event:
                            on_event("token", {"text": chunk})
                if _cancelled():
                    # Leave the socket rather than draining a response nobody
                    # is waiting for.
                    break
                final = stream.get_final_message()
                stop_reason = final.stop_reason
                assistant_content = [self._block_to_dict(b) for b in final.content]
                tool_uses = [b for b in final.content if b.type == "tool_use"]

            if stop_reason == "max_tokens" and cutoffs < _MAX_CUTOFF_RECOVERIES:
                # Cut off mid-output. A half-emitted tool call cannot be
                # executed and cannot be answered with a tool_result, so it is
                # dropped from the transcript and the model is told why.
                cutoffs += 1
                kept = [b for b in assistant_content if b.get("type") == "text"]
                if kept:
                    convo.append({"role": "assistant", "content": kept})
                if step_text.strip():
                    said.append(step_text.strip())
                convo.append({"role": "user", "content": _CUTOFF_NOTICE})
                continue

            convo.append({"role": "assistant", "content": assistant_content})
            if step_text.strip():
                said.append(step_text.strip())

            if stop_reason != "tool_use":
                return TurnResult(text="\n\n".join(said).strip(),
                                  tool_events=tool_events, tier_used=tier)

            calls = [(b.name, dict(b.input)) for b in tool_uses]
            outcomes = _run_tool_calls(calls, tool_executor, parallel_safe, cancel=cancel)

            tool_results = []
            for block, (name, args, result) in zip(tool_uses, outcomes):
                tool_events.append({"name": name, "input": args, "result": result})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _stringify_tool_result(result),
                })
            convo.append({"role": "user", "content": tool_results})

        if _cancelled():
            return TurnResult(text="\n\n".join(said).strip(),
                              tool_events=tool_events, tier_used=tier)
        said.append(
            "(I reached the limit on how many tool calls one turn may make, so this "
            "is as far as I got.)"
        )
        return TurnResult(
            text="\n\n".join(said).strip(),
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


#: How many times one generate() call recovers from output cut off at the
#: token limit before accepting what it has.
_MAX_CUTOFF_RECOVERIES = 2
_CUTOFF_NOTICE = (
    "Your last message was cut off at the output-token limit, so any tool call "
    "in it was NOT executed. Continue from where you stopped. If you were "
    "writing a large file, write it in smaller parts: create it with the first "
    "part, then add the rest with workspace_edit."
)


def _parse_tool_arguments(raw: Any) -> tuple[dict, str]:
    """(arguments, problem). `problem` is set when the model's JSON is unusable."""
    import json
    if isinstance(raw, dict):
        return raw, ""
    if raw in (None, ""):
        return {}, ""
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {}, (f"your tool arguments were not valid JSON ({exc.msg}; "
                        f"position {exc.pos}). This usually means the output was cut off or a "
                        "string was not escaped. Send the call again with complete, "
                        "valid JSON; for a very large file, write it in parts.")
        if isinstance(value, dict):
            return value, ""
    return {}, "tool arguments must be a JSON object"


#: Ceiling on one tool result as the model sees it.
_TOOL_RESULT_CHARS = 8000


def _stringify_tool_result(result: dict) -> str:
    """Serialise a tool result for the model, within budget, as VALID JSON.

    The old `json.dumps(result)[:8000]` cut the document mid-token: the model
    received an unterminated string and no closing braces, and small models
    responded by re-running the tool to "see the rest". Long string fields are
    shortened instead (keeping the head and the tail, where errors live), with
    a marker saying how much was dropped.
    """
    import json
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= _TOOL_RESULT_CHARS:
        return text

    def shrink(value: Any, limit: int) -> Any:
        if isinstance(value, str) and len(value) > limit:
            head = limit * 2 // 3
            tail = limit - head
            return (value[:head] + f"\n…[{len(value) - limit} characters omitted]…\n"
                    + value[-tail:])
        if isinstance(value, list):
            items = [shrink(v, limit) for v in value[:40]]
            if len(value) > 40:
                items.append(f"…[{len(value) - 40} more items omitted]")
            return items
        if isinstance(value, dict):
            return {k: shrink(v, limit) for k, v in value.items()}
        return value

    for limit in (3000, 1500, 700, 300, 120):
        text = json.dumps(shrink(result, limit), ensure_ascii=False, default=str)
        if len(text) <= _TOOL_RESULT_CHARS:
            return text
    return json.dumps({"status": result.get("status"),
                       "error": str(result.get("error") or "")[:1000],
                       "note": "the full result was too large to show"},
                      ensure_ascii=False)


# --------------------------------------------------------------------------- #
#  Offline engine                                                             #
# --------------------------------------------------------------------------- #
class OfflineEngine:
    available = False
    name = "offline"
    streams = False

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

    def translate(self, text: str, _target_language: str) -> str:
        """No translation offline. Hand the text back UNCHANGED.

        This used to prepend a bracketed marker -- "[Automatic translation
        unavailable offline]" -- and return that together with the text. The
        caller writes the result into the mirror-language column, so the marker
        became the first line of the stored answer: a user reading in that
        language opened their answer to an apology in square brackets sitting
        above it, in the wrong language.

        The caller already treats "the translation equals the original" as
        nothing worth writing, and the row already holds readable text in both
        columns. Returning the text unchanged therefore degrades exactly the way
        the design intends -- the same language twice -- rather than degrading
        into a defaced answer."""
        return text

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
        question = user_text.lower()
        # Keep the no-service fallback useful for common statistics lessons.
        # These are stable definitions, not fabricated local facts.
        if "median" in question:
            return (
                "Mediani ni thamani ya katikati baada ya kupanga data kwa mpangilio. "
                "Wastani hupatikana kwa kujumlisha thamani zote na kugawanya kwa idadi yake; "
                "kwa hiyo wastani huathiriwa zaidi na thamani zilizopitiliza."
                if sw else
                "The median is the middle value after ordering the data. The mean is the "
                "sum of all values divided by their count, so extreme values affect the mean more."
            )
        if "wastani" in question or re.search(r"\bmean\b", question):
            return (
                "Wastani ni jumla ya thamani zote ikigawanywa kwa idadi ya thamani. "
                "Kwa mfano, 2, 4 na 6 zina jumla 12; ukigawanya kwa 3 unapata wastani 4."
                if sw else
                "The mean is the sum of all values divided by the number of values. "
                "For example, 2, 4, and 6 sum to 12; dividing by 3 gives a mean of 4."
            )
        if "regression" in question or "urejeleaji" in question:
            return (
                "Urejeleaji (regression) ni mbinu ya kukadiria uhusiano kati ya kigezo cha "
                "matokeo na kigezo kimoja au zaidi cha maelezo. Mgawo huonyesha mwelekeo "
                "na ukubwa wa uhusiano, pamoja na kutokuwa na uhakika kwake."
                if sw else
                "Regression estimates the relationship between an outcome and one or more "
                "explanatory variables. Its coefficients describe the direction and size "
                "of that relationship together with its uncertainty."
            )
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
_engine_retry_at = 0.0
_engine_lock = threading.Lock()


def _try_ollama() -> OllamaEngine | None:
    try:
        eng = OllamaEngine()
        return eng if eng.ping() else None
    except Exception:  # noqa: BLE001 - httpx missing / unreachable
        return None


class CordonEngine(OllamaEngine):
    """The Ollama engine, wired to a Cordon node (see cordon_bridge)."""

    name = "cordon"

    def __init__(self) -> None:
        from .cordon_bridge import cordon_client
        super().__init__(client=cordon_client(settings))

    def model_for_tier(self, tier: str) -> str:
        return settings.cordon_model or "default"

    def resolve_model(self, requested: str | None = None) -> str:
        return settings.cordon_model or "default"


def _try_cordon() -> CordonEngine | None:
    try:
        eng = CordonEngine()
        return eng if eng.ping() else None
    except Exception:  # noqa: BLE001 - unreachable / misconfigured
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
    import time

    global _engine, _engine_retry_at
    if settings.force_offline_llm or (settings.llm_backend or "auto").lower() == "offline":
        if _engine is None or _engine.name != "offline":
            _engine = OfflineEngine()
        return _engine

    now = time.monotonic()
    if _engine is not None and (_engine.name != "offline" or now < _engine_retry_at):
        return _engine

    # A locally installed model server often starts after Weave. Keep the
    # offline engine responsive, but retry discovery periodically instead of
    # locking the process into offline mode for its entire lifetime.
    with _engine_lock:
        now = time.monotonic()
        if _engine is not None and (_engine.name != "offline" or now < _engine_retry_at):
            return _engine

        _engine_retry_at = now + 15.0
        backend = (settings.llm_backend or "auto").lower()
        if backend == "ollama":
            _engine = _try_ollama() or OfflineEngine()
        elif backend == "cordon":
            _engine = _try_cordon() or OfflineEngine()
        elif backend == "anthropic":
            _engine = _try_anthropic() or OfflineEngine()
        else:  # auto
            _engine = _try_ollama() or _try_anthropic() or OfflineEngine()
        return _engine


def reset_engine() -> None:
    """Test hook."""
    global _engine, _engine_retry_at
    with _engine_lock:
        _engine = None
        _engine_retry_at = 0.0
