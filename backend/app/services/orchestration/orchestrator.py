"""Orchestration Service (architecture 5.1 #2, section 6).

Owns all LLM calls, prompt construction, mode logic, conversation state, and the
bilingual data layer. It wires together retrieval (grounding), the sandbox (via
the Analysis Service), and the guardrails into a single execute-and-explain loop
(Design Principle 1: one reasoning engine, two framings).

Exposes `stream_turn` — a generator of Server-Sent-Event payloads (architecture
4.1 / 3 step 6) — and `run_turn` for non-streaming callers/tests.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from sqlalchemy.orm import Session

from ...models import Dataset, Message, Project
from ..analysis import get_analysis_service
from ..memory import get_memory_service
from ..render import get_render
from ..retrieval import get_retrieval_service
from ..tools import ToolContext, get_registry
from ..warehouse import get_warehouse
from ..websearch import get_web_search
from ..workspace import get_workspace_service
from . import guardrails, prompts
from .llm import OfflineEngine, TurnResult, get_engine
from .router import classify

log = logging.getLogger("weave.orchestrator")

TEMPLATE_ANALYSIS = """import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt

df = weave_io.load_dataset()
print("Shape:", df.shape)
print("\\nSummary statistics:")
print(df.describe(include="all").to_string())

num = df.select_dtypes("number")
if num.shape[1] >= 1:
    num.iloc[:, :4].hist(figsize=(8, 6))
    fig = plt.gcf()
    fig.suptitle("Distributions")
    weave_io.save_output(fig, "distributions.png")

if num.shape[1] >= 2:
    corr = num.corr(numeric_only=True)
    print("\\nCorrelation matrix:")
    print(corr.round(3).to_string())
    weave_io.save_output(corr.reset_index(), "correlation.csv")
"""

class Orchestrator:
    def __init__(self) -> None:
        self.retrieval = get_retrieval_service()
        self.analysis = get_analysis_service()
        self.memory = get_memory_service()

    # -- public: non-streaming ----------------------------------------------

    def run_turn(
        self, db: Session, project: Project, user_text: str, language: str,
        dataset_id: str | None = None, effort: str | None = None, model: str | None = None,
        thread_id: str | None = None,
    ) -> Message:
        assistant_msg, _ = self._process(db, project, user_text, language, dataset_id,
                                         effort=effort, model=model, thread_id=thread_id)
        return assistant_msg

    # -- public: streaming (SSE) --------------------------------------------

    def stream_turn(
        self, db: Session, project: Project, user_text: str, language: str,
        dataset_id: str | None = None, effort: str | None = None, model: str | None = None,
        regenerate: bool = False, services_pref: dict | None = None,
        thread_id: str | None = None, channel: str = "chat",
        frames: list[str] | None = None,
    ) -> Iterator[dict]:
        """Yield SSE events LIVE. The turn runs in a worker thread; _process emits
        every event onto a queue which this generator drains in real time. If the
        client disconnects (Stop), a GeneratorExit fires here and we set a cancel
        Event that _process / the Ollama stream loop check to abort promptly."""
        import queue
        import threading

        q: "queue.Queue" = queue.Queue()
        holder: dict = {}
        cancel = threading.Event()

        def emit(event: str, data: dict) -> None:
            # The turn id is learned by watching the stream rather than being
            # returned by _process, because it has to be known on the FAILURE
            # paths too — a turn that raised halfway still holds a steering
            # registration, and only the finally below can release it.
            if event == "meta" and data.get("message_id"):
                holder["turn_id"] = data["message_id"]
            q.put({"event": event, "data": data})

        def worker() -> None:
            try:
                msg, meta = self._process(db, project, user_text, language, dataset_id,
                                          emit=emit, effort=effort, model=model,
                                          cancel=cancel, regenerate=regenerate,
                                          services_pref=services_pref, thread_id=thread_id,
                                          channel=channel, frames=frames)
                holder["msg"] = msg
                holder["meta"] = meta
            except Exception as exc:  # noqa: BLE001
                holder["error"] = str(exc)
            finally:
                if holder.get("turn_id"):
                    from ..steering import get_steering
                    get_steering().finish(holder["turn_id"])
                q.put(None)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        try:
            yield {"event": "status", "data": {"phase": "thinking"}}
            while True:
                try:
                    item = q.get(timeout=10)
                except queue.Empty:
                    yield {"event": "ping", "data": {}}
                    continue
                if item is None:
                    break
                yield item
            t.join()
            if "error" in holder:
                yield {"event": "error", "data": {"message": holder["error"]}}
                return
            meta = holder.get("meta") or {}
            yield {"event": "done", "data": {
                "message_id": holder.get("msg").id if holder.get("msg") else None,
                "thread_id": meta.get("thread_id"),
                # Set when this turn filled the window and a successor thread was
                # opened. The client switches to it rather than silently writing
                # the next turn into a thread the model can no longer read.
                "next_thread_id": meta.get("next_thread_id"),
                "context_used": meta.get("context_used"),
                "context_window": meta.get("context_window"),
            }}
        except GeneratorExit:
            # client disconnected (Stop) — signal the worker to abort promptly
            cancel.set()
            raise

    # -- core ----------------------------------------------------------------

    def _process(
        self, db: Session, project: Project, user_text: str, language: str,
        dataset_id: str | None, emit=None, effort: str | None = None, model: str | None = None,
        cancel=None, regenerate: bool = False, services_pref: dict | None = None,
        thread_id: str | None = None, channel: str = "chat",
        frames: list[str] | None = None,
    ) -> tuple[Message, dict]:
        engine = get_engine()

        # 0. resolve the thread this turn belongs to, and the REAL context window
        # of the model that will answer it. Every downstream budget (history
        # trimming, rollover, the UI meter) is derived from this one number, so
        # they can never disagree.
        thread = self.memory.get_thread(db, project, thread_id)
        context_window = self._context_window(engine, model)

        # 1. persist the user's message. On regenerate we reuse the last user turn
        # and drop the previous assistant answer instead of duplicating.
        if regenerate:
            last_user = (
                db.query(Message).filter(Message.thread_id == thread.id, Message.role == "user")
                .order_by(Message.created_at.desc()).first()
            )
            last_asst = (
                db.query(Message).filter(Message.thread_id == thread.id, Message.role == "assistant")
                .order_by(Message.created_at.desc()).first()
            )
            if last_asst:
                db.delete(last_asst)
                db.commit()
            user_msg = last_user or self._store_message(db, project, "user", user_text, language,
                                                        engine, thread)
            user_text = user_msg.content_en or user_msg.content_sw or user_text
        else:
            user_msg = self._store_message(db, project, "user", user_text, language, engine, thread)
            self.memory.rename_if_untitled(db, thread, user_text)

        # 2. route (model tiering + intent) — architecture 6.4
        route = classify(user_text, project.mode)

        # 3. dataset context
        dataset = None
        if dataset_id:
            dataset = db.query(Dataset).filter(
                Dataset.id == dataset_id, Dataset.project_id == project.id
            ).first()
        dataset_profile = dataset.column_profile if dataset else None

        # 4. retrieval before generation (principle 3) — always for factual intents
        passages: list[dict] = []
        if route.needs_retrieval or route.intent in {"literature", "concept"}:
            passages = self.retrieval.search(db, user_text, language=language)

        # 5. integrity guard (architecture 6.5)
        integrity = guardrails.triggers_integrity_guard(user_text, project.mode)

        # 6. assistant placeholder so tool executions can link to it
        assistant_msg = Message(
            project_id=project.id, thread_id=thread.id, role="assistant",
            content_sw="", content_en="", original_language=language,
            tool_calls=[], citations=[],
        )
        db.add(assistant_msg)
        db.flush()

        # -- capability bus: registry + per-turn context ----------------------
        trust = getattr(getattr(project, "user", None), "trust_tier", "verified") or "verified"
        services = {"analysis": self.analysis, "retrieval": self.retrieval,
                    "memory": self.memory}
        web = get_web_search()
        if web.enabled:
            services["websearch"] = web
        render = get_render()
        if render.enabled:
            services["render"] = render
        warehouse = get_warehouse()
        if warehouse.enabled:
            services["warehouse"] = warehouse
        workspace = get_workspace_service()
        if workspace.enabled:
            services["workspace"] = workspace
        from ..skills import get_skills
        skills = get_skills()
        if skills.enabled:
            services["skills"] = skills
        # The shared canvas needs a database session to read and write through,
        # so it is only offered on turns that have one.
        if db is not None:
            from ..canvas import get_canvas_service
            services["canvas"] = get_canvas_service()
        # `ask_user` is only offered when there is a live client to answer it.
        # In a batch/WhatsApp turn a blocking question would simply hang.
        if emit is not None:
            services["interactive"] = True

        progress_events: list[dict] = []

        def _emit(event: str, data: dict) -> None:
            # Live sink (SSE) when streaming; always also collected for run_turn/meta.
            progress_events.append({"event": event, "data": data})
            if emit is not None:
                emit(event, data)

        ctx = ToolContext(
            db=db, project=project, dataset=dataset, message_id=assistant_msg.id,
            language=language, trust=trust, services=services, emit=_emit,
            thread=thread, cancel=cancel,
        )
        registry = get_registry()
        # A user who has switched a service ON in the composer wants it available
        # regardless of what the intent router inferred — an explicit preference
        # outranks a heuristic. Intent gating still applies to everything else.
        forced = {k for k, v in (services_pref or {}).items() if v}
        tool_schemas = registry.schemas(mode=project.mode, trust=trust, services=services,
                                        intent=route.intent, force=forced)

        # meta up front so the client has the message id immediately
        _emit("meta", {"message_id": assistant_msg.id, "intent": route.intent,
                       "mode": project.mode, "effort": (effort or "weave"),
                       "thread_id": thread.id, "context_window": context_window,
                       # The client may redirect this turn from now on.
                       "steerable": emit is not None})

        # Register for steering HERE, not at the generation call: the client has
        # the turn id from the event above, and retrieval plus pre-generation
        # tools can run for a long time before generation starts. A redirect sent
        # in that window must be queued, not rejected for an unknown turn.
        #
        # Only for streaming turns. A batch turn (WhatsApp, run_turn) has no live
        # client to send a redirect, so registering one would leak an entry until
        # the sweeper collected it. `stream_turn` deregisters on every exit path.
        from ..steering import get_steering as _get_steering
        _steering = _get_steering()
        _steer_turn = (
            _steering.register(
                turn_id=assistant_msg.id,
                user_id=str(getattr(getattr(project, "user", None), "id", "") or ""),
                project_id=str(project.id),
            )
            if emit is not None
            else None
        )

        tool_events: list[dict] = []
        from ...config import settings as _s
        _counts = {"sandbox": 0, "web": 0, "exec": 0}
        _web_tools = {"web_search", "deep_research"}

        _step_seq = {"n": 0}

        # The artifact gate. Nothing a tool renders reaches the transcript until
        # it has been opened in a real browser — see services/orchestration/
        # verification.py for why this cannot be left to the model's discretion.
        from .verification import MAX_REPAIRS, ArtifactGate
        gate = ArtifactGate(str(project.id))

        def tool_executor(name: str, tool_input: dict) -> dict:
            # Per-turn caps: a runaway agentic loop must not hammer the sandbox or
            # crawl the web unboundedly (defence-in-depth atop the iter limit).
            if name == "run_analysis":
                _counts["sandbox"] += 1
                if _counts["sandbox"] > _s.max_sandbox_runs_per_turn:
                    return {"status": "rejected", "error": "sandbox run limit reached for this turn"}
            if name in _web_tools:
                _counts["web"] += 1
                if _counts["web"] > _s.max_web_calls_per_turn:
                    return {"status": "rejected", "error": "web call limit reached for this turn"}
            if name == "workspace_exec":
                # Each exec starts a container; a looping agent would otherwise
                # spawn hundreds in a single turn.
                _counts["exec"] += 1
                if _counts["exec"] > _s.max_workspace_execs_per_turn:
                    return {"status": "rejected",
                            "error": "workspace command limit reached for this turn"}

            tool_input = dict(tool_input or {})
            # `note` is the model-authored step title. It is a UI concern, never a
            # tool argument, so it is stripped before execution. When the model
            # omits it (small local models often do) the client falls back to a
            # deterministic title derived from the tool and its arguments, so the
            # step chip is never blank and never waits on the model.
            note = tool_input.pop("note", None)

            _step_seq["n"] += 1
            step_id = f"st{_step_seq['n']}"
            _emit("step_start", {
                "id": step_id,
                "tool": name,
                "args": _preview_args(tool_input),
                **({"title": str(note)[:120]} if note else {}),
            })

            # Tell the client an artifact is COMING so it can reserve space and
            # show a shaped skeleton ("a chart is being drawn") instead of the
            # answer suddenly jumping when the real thing lands. Rendering a
            # deck or a simulation can take many seconds; an unannounced gap
            # reads as a hang.
            pending_kind = _PENDING_ARTIFACT_KIND.get(name)
            if pending_kind:
                _emit("artifact_pending", {
                    "id": step_id,
                    "kind": pending_kind,
                    "tool": name,
                    "title": str(tool_input.get("title") or note or "").strip()[:120],
                })

            # --- gated execution ------------------------------------------
            # An artifact-producing tool pushes its output into the transcript
            # the instant the render service accepts it. That is exactly the
            # emit-and-continue behaviour we are removing, so for gated tools
            # the `artifact` events are BUFFERED here and released only once the
            # page has been proven to open. Buffering at the emit boundary keeps
            # every tool implementation untouched.
            gated = gate.gates(name)
            buffered: list[dict] = []
            saved_emit = ctx.emit
            if gated:
                def _capture(event: str, data: dict) -> None:
                    if event == "artifact":
                        buffered.append(dict(data))
                        return
                    saved_emit(event, data)

                ctx.emit = _capture

            try:
                result = registry.execute(name, ctx, tool_input)
            finally:
                if gated:
                    ctx.emit = saved_emit

            verdict = None
            if gated:
                _emit("verify_start", {"id": step_id, "tool": name})
                verdict = gate.check(name, tool_input, result)
                _emit("verify_end", {
                    "id": step_id,
                    "tool": name,
                    "checked": verdict.checked,
                    "ok": verdict.ok,
                    "attempt": verdict.attempt,
                    "max_attempts": MAX_REPAIRS,
                    "exhausted": verdict.exhausted,
                    "errors": verdict.errors[:4],
                    "warnings": verdict.warnings[:3],
                    "summary": verdict.summary,
                    "ms": verdict.duration_ms,
                })
                if verdict.released:
                    from ...security import sign_path as _sign
                    preview = ""
                    if verdict.screenshot_key:
                        preview = (f"/api/artifact/{verdict.screenshot_key}"
                                   f"?sig={_sign(verdict.screenshot_key)}")
                    for art in buffered:
                        # A real screenshot of the real page: proof it rendered,
                        # and a poster frame so a transcript full of 3D scenes
                        # does not need a dozen live WebGL contexts at once.
                        if preview:
                            art["preview"] = preview
                        art["verified"] = verdict.ok
                        if not verdict.ok:
                            art["defects"] = verdict.errors[:4]
                        _emit("artifact", art)
                result = ArtifactGate.apply(result, verdict, name)

            # Always resolve the placeholder — on failure too, or the skeleton
            # would shimmer forever.
            if pending_kind:
                _emit("artifact_pending_done", {
                    "id": step_id,
                    "ok": bool(result.get("output_files")),
                })

            status = result.get("status", "ok")
            _emit("step_end", {
                "id": step_id,
                "tool": name,
                "status": status,
                "summary": _summarise(name, result),
                # What the tool actually produced, so an expanded step is an
                # audit record rather than an empty drawer. Most tools emit no
                # incremental substeps at all (only deep_research does), so
                # without this the collapsible had literally nothing to show.
                "detail": _detail(name, tool_input, result),
                **({"error": str(result.get("error"))[:400]} if result.get("error") else {}),
            })
            tool_events.append({"name": name, "input": tool_input, "result": result})
            return result

        # 6b. Retrieval-before-generation, extended to the web (Principle 3): only
        # for LITERATURE intent ("what does the research/web say"). Concept
        # explanations answer from the model's knowledge (+ grounding guard) rather
        # than triggering a web crawl — this stops the "web-searched 'standard
        # deviation'" over-eagerness.
        if not passages and route.intent == "literature" and "websearch" in services:
            web = tool_executor("deep_research", {"query": user_text})
            if web.get("status") == "ok" and web.get("passages"):
                passages = web["passages"][:6]

        # 7. generate
        translate_fn = engine.translate
        engine_streamed = False
        history_trimmed = False
        if getattr(engine, "available", False):
            system = self._system_prompt(project, language, passages, dataset_profile, integrity,
                                         effort, thread=thread, db=db,
                                         capabilities=set(services.keys()),
                                         model_class=self._model_class(engine, model),
                                         channel=channel)
            messages, history_trimmed = self._history_as_messages(
                db, thread, language, up_to=user_msg, context_window=context_window,
            )
            # Screen-share frames ride on the LAST user message, in the
            # engine-neutral `images` shape Ollama consumes natively and the
            # Anthropic engine converts (see `AnthropicEngine._with_images`).
            # They are attached here rather than persisted with the message: a
            # screenshot is context for one turn, and storing every frame would
            # grow the conversation without making the next answer better.
            if frames and messages and messages[-1].get("role") == "user":
                messages[-1] = {**messages[-1], "images": list(frames)[:2]}
            if history_trimmed:
                # Say so. Silently dropping the start of a conversation is how a
                # model appears to "forget" what was agreed, with no signal to
                # the reader that anything was lost.
                _emit("context_trimmed", {
                    "thread_id": thread.id, "context_window": context_window,
                })
            # --- steerable generation ---------------------------------------
            # The turn is registered under the assistant message id, which the
            # client already has from the `meta` event above. A redirect POSTed
            # while this runs aborts the generation (the engines poll the cancel
            # object between tokens and between tool calls), lands in the
            # conversation as a real user turn, and generation restarts from
            # there. See services/steering.py for why restarting beats splicing.
            from ..steering import SteerAwareCancel
            steering = _steering
            steer_cancel = (
                SteerAwareCancel(cancel, _steer_turn.event) if _steer_turn else cancel
            )
            try:
                _emit("answer_start", {})
                while True:
                    result: TurnResult = engine.generate(
                        system=system, messages=messages, tools=tool_schemas,
                        tool_executor=tool_executor, tier=route.tier,
                        on_event=_emit, effort=effort, model=model,
                        cancel=steer_cancel,
                    )
                    answer = result.text
                    tool_events = result.tool_events
                    tier_used = result.tier_used
                    engine_streamed = getattr(engine, "name", "") == "ollama"

                    if _steer_turn is None:
                        break
                    redirects = steering.drain(assistant_msg.id)
                    if not redirects or steer_cancel.cancelled:
                        break
                    if steering.restarts_left(assistant_msg.id) <= 0:
                        # Out of budget: still deliver the redirect so it is not
                        # silently swallowed, but stop restarting so the turn
                        # terminates. It becomes context for the next turn.
                        for r in redirects:
                            _emit("steer_deferred", {"text": r["text"]})
                        break

                    steering.note_restart(assistant_msg.id)
                    for r in redirects:
                        # A redirect is a user instruction, so it enters the
                        # conversation as one. Marking it as mid-stream is what
                        # tells the model this supersedes the direction it was
                        # taking rather than being a fresh, separate request.
                        messages.append({
                            "role": "user",
                            "content": (
                                "[REDIRECT — sent while you were still working, and it "
                                "supersedes the direction you were taking] " + r["text"]
                            ),
                        })
                        _emit("steer_applied", {
                            "text": r["text"], "kind": r.get("kind", "redirect"),
                            "restarts_left": steering.restarts_left(assistant_msg.id),
                        })
                    # Everything streamed so far was reasoning the user has now
                    # overridden. Tell the client to clear it, so what is on
                    # screen matches what the model actually reasoned about.
                    _emit("answer_restart", {"reason": "steered"})
            except Exception as exc:  # noqa: BLE001
                # Remote LLM (Ollama/Anthropic) failed after retries -> degrade to
                # the offline engine so the turn still completes rather than 500s.
                log.warning("LLM engine '%s' failed (%s); falling back to offline",
                            getattr(engine, "name", "?"), exc)
                answer, tier_used = self._offline_turn(
                    project, language, route, user_text, passages, integrity,
                    dataset, tool_events, tool_executor, web_enabled="websearch" in services,
                )
                translate_fn = OfflineEngine().translate
        else:
            answer, tier_used = self._offline_turn(
                project, language, route, user_text, passages, integrity,
                dataset, tool_events, tool_executor, web_enabled="websearch" in services,
            )
            translate_fn = OfflineEngine().translate

        # If the engine did not stream tokens live (offline / anthropic / fallback),
        # stream the finished answer now so the UI still animates it in.
        if not engine_streamed and emit is not None:
            for tok in _stream_tokens(answer):
                _emit("token", {"text": tok})

        # 8. post-hoc grounding / hallucination guard v2 (architecture 6.5)
        grounded, grounding_note = guardrails.check_grounding(answer, bool(passages), passages)

        # 9. fill the assistant message + citations + tool_calls.
        #
        # The mirror-language column is filled with the ORIGINAL text here and
        # translated in the background afterwards. Translating inline used to
        # cost a whole extra blocking LLM round-trip between the last streamed
        # token and the `done` event — 6-10s of the UI sitting there looking
        # frozen with the answer already fully rendered. Nothing on screen needs
        # the other language until the user actually toggles it.
        assistant_msg.content_sw = answer
        assistant_msg.content_en = answer
        citations = self._collect_citations(passages, tool_events)
        artifacts = _artifacts_from_events(progress_events)
        images = self._collect_web_images(tool_events, passages)
        assistant_msg.citations = citations
        # Persist the STEP TIMELINE, not just a list of tool names. Reloading a
        # conversation used to drop every tool panel on the floor: the work the
        # assistant did — what it searched, what it ran, what each step produced
        # — existed only in the live SSE stream, so a refresh turned a detailed
        # audit trail into a bare paragraph. `_step_timeline` reconstructs it
        # from the events the client actually received, which keeps the replayed
        # transcript identical to the live one by construction.
        assistant_msg.tool_calls = _step_timeline(progress_events)
        # persist artifacts + images on the message so history re-renders them
        assistant_msg.artifacts = artifacts
        assistant_msg.images = images
        db.add(assistant_msg)

        # 9b. Offer the domains this turn consulted as crawl candidates, so the
        # library grows with real use. Consent-gated; creates nothing enabled.
        self._note_session_sources(db, project, tool_events)

        # 10. rolling project summary (architecture 6.2 project-memory layer)
        self._update_summary(project, user_text, answer)
        db.add(project)
        self.memory.touch(db, thread)
        db.commit()
        db.refresh(assistant_msg)

        # 11. emit images, artifacts and citations (live)
        if images:
            _emit("images", {"images": images})
        for a in artifacts:
            _emit("artifact", a)
        for c in citations:
            _emit("citation", c)

        # 12. translate the mirror column OFF the critical path.
        self._translate_in_background(assistant_msg.id, answer, language, translate_fn)

        # 13. context rollover. If this thread has now outgrown the model's
        # window, summarise it and open a successor so the NEXT turn starts with
        # a recap instead of a silently truncated history. Done after the answer
        # is committed, so a summarisation failure can never lose the turn.
        next_thread_id = None
        if self.memory.should_roll(db, thread, context_window):
            try:
                _emit("summarizing", {"thread_id": thread.id})
                successor = self.memory.roll_thread(db, project, thread, engine)
                next_thread_id = successor.id
                _emit("thread_rolled", {
                    "from": thread.id,
                    "to": successor.id,
                    "title": successor.title,
                    "summary": successor.summary[:600],
                })
            except Exception as exc:  # noqa: BLE001 - never fail a delivered turn
                log.warning("thread rollover failed for %s: %s", thread.id, exc)
                db.rollback()

        meta = {
            "intent": route.intent, "tier": tier_used, "grounded": grounded,
            "grounding_note": grounding_note if not grounded else "",
            "tool_events": tool_events, "progress": progress_events,
            "artifacts": artifacts, "images": images,
            "thread_id": thread.id, "next_thread_id": next_thread_id,
            "context_window": context_window,
            "context_used": thread.token_estimate,
            "history_trimmed": history_trimmed,
        }
        return assistant_msg, meta

    @staticmethod
    def _context_window(engine, model: str | None) -> int:
        """The selected model's REAL context window.

        Single source of truth: the number sent as Ollama's `num_ctx`, the
        number history is trimmed against, and the number the UI meter is drawn
        against are all this one value. When they diverge the meter lies, which
        is worse than showing no meter at all.
        """
        from ...config import settings as _s
        try:
            if hasattr(engine, "effective_context"):
                name = model or engine.model_for_tier("fast")
                return int(engine.effective_context(name))
        except Exception:  # noqa: BLE001 - unreachable server: fall back, don't fail
            pass
        return _s.ollama_num_ctx

    @staticmethod
    def _model_class(engine, model: str | None) -> str:
        """"large" or "small" — how much prompt guidance is worth its tokens.

        Both classes get the same RULES; the difference is how much explanatory
        text accompanies them. A 3B local model handed eight pages of working
        standards produces worse output than the same model handed two, because
        it spends its attention on the instructions rather than the task.

        The engine classifies when it can, because it knows what the server
        actually reports — parameter count and whether the model advertises
        reasoning. Only when it cannot do we fall back to reading the name, and
        that fallback is why `minimax-m3:cloud` and `gemma4:cloud` were being
        handed the cut-down prompt meant for a 3B model: neither tag contains a
        parameter count to match on.
        """
        import re

        if type(engine).__name__ == "AnthropicEngine":
            return "large"
        name = model or getattr(engine, "model", "") or ""
        classifier = getattr(engine, "model_class", None)
        if callable(classifier):
            try:
                resolved = getattr(engine, "resolve_model", lambda n: n)(name) if name else name
                return classifier(resolved or engine.model_for_tier("fast"))
            except Exception:  # noqa: BLE001 - unreachable server: fall through
                pass
        low = name.lower()
        if low.endswith(":cloud") or ":cloud-" in low:
            return "large"
        match = re.search(r"[:\-](\d+(?:\.\d+)?)\s*b\b", low)
        if match:
            try:
                return "large" if float(match.group(1)) >= 27 else "small"
            except ValueError:
                pass
        return "small"

    def _collect_artifacts(self, tool_events: list[dict]) -> list[dict]:
        """Kept for callers outside the turn loop (tests, batch channels).

        The live path uses `_artifacts_from_events` instead — see its docstring
        for why deriving from what the client was actually sent is the only way
        history and the live transcript stay identical.
        """
        from ...security import sign_path
        arts: list[dict] = []
        for e in tool_events:
            for f in e.get("result", {}).get("output_files", []) or []:
                key = f.get("s3_key")
                if not key:
                    continue
                arts.append({
                    "name": f.get("name"), "mime": f.get("mime", "application/octet-stream"),
                    "bytes": f.get("bytes", 0), "tool": e.get("name"),
                    "url": f"/api/artifact/{key}?sig={sign_path(key)}",
                })
        return arts

    def _collect_web_images(self, tool_events: list[dict], passages: list[dict]) -> list[dict]:
        """Top web images gathered during search (rendered as a grid in chat)."""
        imgs: list[dict] = []
        seen = set()
        for e in tool_events:
            for im in e.get("result", {}).get("images", []) or []:
                u = im.get("url")
                if u and u not in seen:
                    seen.add(u)
                    imgs.append({"url": u, "title": im.get("title", ""), "source": im.get("source", "")})
        return imgs[:4]

    def _note_session_sources(self, db, project, tool_events: list[dict]) -> None:
        """Record the DOMAINS this turn actually consulted as crawl candidates.

        This is the mechanism that makes the library grow with real use rather
        than only with an operator's attention: the pages people genuinely read
        are a far better signal of what belongs in a Tanzanian research library
        than anything we would guess.

        Three properties make it defensible:
          * it is per-user consent — `User.allow_source_crawl`, on by default and
            switchable off in Settings, and checked inside the crawler service so
            there is exactly one place it can be got wrong;
          * it records a DOMAIN as a DISABLED candidate and crawls nothing. An
            operator approves it on the admin page before a single page is
            fetched, so one odd link in one chat cannot start a crawl;
          * it never touches anything the user wrote — only public URLs the
            session already fetched.

        Failures here are swallowed: growing the library is a background nicety
        and must never affect the answer the user is waiting for.
        """
        user = getattr(project, "user", None)
        if user is None or not getattr(user, "allow_source_crawl", True):
            return
        urls: list[str] = []
        for event in tool_events:
            result = event.get("result") or {}
            if result.get("url"):
                urls.append(str(result["url"]))
            for passage in result.get("passages", []) or []:
                if isinstance(passage, dict) and passage.get("url"):
                    urls.append(str(passage["url"]))
            for row in result.get("results", []) or []:
                if isinstance(row, dict) and row.get("url"):
                    urls.append(str(row["url"]))
        if not urls:
            return
        try:
            from ..crawler import get_crawler
            crawler = get_crawler()
            seen_domains: set[str] = set()
            for url in urls[:20]:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.lower()
                if not domain or domain in seen_domains:
                    continue
                seen_domains.add(domain)
                crawler.note_session_source(db, url, user)
        except Exception as exc:  # noqa: BLE001
            log.debug("could not record session sources: %s", exc)

    # -- helpers -------------------------------------------------------------

    def _offline_turn(self, project, language, route, user_text, passages, integrity,
                      dataset, tool_events, tool_executor, web_enabled=False) -> tuple[str, str]:
        """Deterministic offline composition. Drives the sandbox for data questions
        unless an analysis was already run this turn (avoids double execution when
        used as a fallback after a partial agentic run)."""
        analysis_result = next(
            (e["result"] for e in tool_events if e.get("name") == "run_analysis"), None
        )
        if analysis_result is None and route.needs_sandbox and dataset is not None:
            analysis_result = tool_executor("run_analysis", {"code": TEMPLATE_ANALYSIS})

        # If there's no local grounding for a factual question, fall back to a
        # live deep-web-research pass (only when the web-search service is on).
        if web_enabled and not passages and route.intent == "literature":
            already = next((e["result"] for e in tool_events if e.get("name") == "deep_research"), None)
            web = already or tool_executor("deep_research", {"query": user_text})
            if web.get("status") == "ok" and web.get("passages"):
                passages = web["passages"][:6]

        answer = OfflineEngine().compose(
            language=language, mode=project.mode, intent=route.intent,
            user_text=user_text, passages=passages, analysis=analysis_result,
            integrity_triggered=integrity,
        )
        return answer, "offline"

    def _translate_in_background(self, message_id: str, answer: str, language: str,
                                 translate_fn) -> None:
        """Fill the mirror-language column after the turn has already finished.

        Runs on its own daemon thread with its OWN database session — a Session
        is not thread-safe and the request-scoped one is closed the moment the
        SSE response completes. Failure is silent by design: the row already
        holds readable text in both columns, so a failed translation degrades to
        "same language twice" rather than to an empty message.
        """
        import threading

        target = "en" if language == "sw" else "sw"
        column = "content_en" if target == "en" else "content_sw"

        def work() -> None:
            from ...db import SessionLocal
            try:
                translated = self._safe_translate(translate_fn, answer, target)
            except Exception:  # noqa: BLE001 - never let a background thread raise
                return
            if not translated or translated.strip() == answer.strip():
                return
            session = SessionLocal()
            try:
                msg = session.get(Message, message_id)
                if msg is not None:
                    setattr(msg, column, translated)
                    session.add(msg)
                    session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
            finally:
                session.close()

        threading.Thread(target=work, daemon=True, name="weave-translate").start()

    @staticmethod
    def _safe_translate(translate_fn, text: str, target: str) -> str:
        """Never let a translation failure sink the turn — fall back to the offline
        marker (or the original text) if the translating engine errors."""
        try:
            return translate_fn(text, target)
        except Exception:  # noqa: BLE001
            try:
                return OfflineEngine().translate(text, target)
            except Exception:  # noqa: BLE001
                return text

    def _system_prompt(self, project, language, passages, dataset_profile, integrity,
                       effort=None, thread=None, db=None, capabilities=None,
                       model_class: str = "large", channel: str = "chat") -> str:
        from ...runtime import effort_spec
        base = prompts.assemble_system_prompt(
            mode=project.mode, language=language, passages=passages,
            project_summary=project.summary, hypotheses=project.hypotheses or [],
            dataset_profile=dataset_profile, capabilities=capabilities,
            model_class=model_class, channel=channel,
        )
        # Cross-thread memory: what makes a NEW chat in an existing project
        # continuous rather than amnesiac.
        if thread is not None and db is not None:
            block = self.memory.context_block(db, project, thread, language)
            if block:
                base += "\n\n" + block
        base += "\n\n" + effort_spec(effort)["prompt"]
        if integrity:
            base += "\n\n" + guardrails.integrity_redirect_instruction(language)
        return base

    def _history_as_messages(
        self, db, thread, language, up_to: Message, context_window: int,
    ) -> tuple[list[dict], bool]:
        """History for this turn, budgeted against the model's real window.

        The old version took a fixed last-12 slice of the PROJECT's messages.
        That was wrong twice over: it ignored how large the turns actually were
        (twelve long analyses overflow an 8k window; twelve one-liners waste a
        128k one), and with threads it would mix unrelated conversations.
        """
        out, trimmed = self.memory.history_for(
            db, thread, language, context_window=context_window,
        )
        # The just-stored user message must be last, whatever the trim did.
        if not out or out[-1]["role"] != "user":
            out.append({
                "role": "user",
                "content": up_to.content_sw if language == "sw" else up_to.content_en,
            })
        return out, trimmed

    def _collect_citations(self, passages: list[dict], tool_events: list[dict]) -> list[dict]:
        cites: list[dict] = []
        seen = set()

        def add(p: dict) -> None:
            cid = p.get("chunk_id") or p.get("source_id")
            if cid in seen:
                return
            seen.add(cid)
            cites.append({
                "source_id": p.get("source_id"), "title": p.get("title"),
                "url": p.get("url"), "source_type": p.get("source_type"),
                "access_status": p.get("access_status"), "predatory_flag": p.get("predatory_flag"),
            })

        for p in passages[:5]:
            add(p)
        for e in tool_events:
            name = e.get("name")
            result = e.get("result", {})
            if name == "search_library":
                for p in result.get("results", [])[:5]:
                    add(p)
            elif name == "deep_research":
                for p in result.get("passages", [])[:5]:
                    add(p)
            elif name == "web_search":
                for r in result.get("results", [])[:5]:
                    add({"source_id": r.get("url"), "title": r.get("title"),
                         "url": r.get("url"), "source_type": "web",
                         "access_status": "open", "predatory_flag": False})
        return cites

    def _store_message(self, db, project, role, text, language, engine, thread=None) -> Message:
        # A user's own words are never machine-translated for storage — the literal
        # text is kept in both columns so the bilingual toggle always shows exactly
        # what they typed. (Assistant answers ARE translated, in _process.)
        content_sw = content_en = text
        msg = Message(
            project_id=project.id, thread_id=thread.id if thread is not None else None,
            role=role, original_language=language,
            content_sw=content_sw, content_en=content_en, tool_calls=[], citations=[],
        )
        db.add(msg)
        db.flush()
        return msg

    def _update_summary(self, project: Project, user_text: str, answer: str) -> None:
        prior = project.summary or ""
        addition = f"Q: {user_text[:160]} | A: {answer[:160]}"
        combined = (prior + "\n" + addition).strip()
        # keep it short for cheap context reuse (rolling summarization)
        project.summary = combined[-1200:]

    def resummarize_project(self, db: Session, project: Project) -> None:
        """Regenerate a clean project summary from its messages via the LLM
        (architecture 6.2 rolling summarization). Falls back to the heuristic string
        if no LLM engine is available."""
        engine = get_engine()
        msgs = (
            db.query(Message).filter(Message.project_id == project.id)
            .order_by(Message.created_at).all()
        )
        transcript = "\n".join(
            f"{m.role}: {(m.content_en or m.content_sw)[:300]}" for m in msgs[-24:]
        )[:6000]
        if getattr(engine, "available", False) and transcript.strip():
            try:
                sys_p = ("Summarise this research/study conversation into a compact memory: key "
                         "questions explored, findings, datasets, and open threads. <= 120 words.")
                if hasattr(engine, "_post_chat"):
                    r = engine._post_chat({"model": engine.model_for_tier("fast"), "stream": False,
                                           "messages": [{"role": "system", "content": sys_p},
                                                        {"role": "user", "content": transcript}]})
                    project.summary = (r.json().get("message", {}).get("content") or "")[:1500]
                else:
                    r = engine._client.messages.create(model=engine.model_for_tier("fast"),
                                                       max_tokens=300, system=sys_p,
                                                       messages=[{"role": "user", "content": transcript}])
                    project.summary = "".join(b.text for b in r.content if b.type == "text")[:1500]
            except Exception:  # noqa: BLE001
                project.summary = transcript[-1200:]
        else:
            project.summary = transcript[-1200:]
        db.add(project)
        db.commit()


_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


#: Argument values above this length are truncated before being sent to the UI.
_ARG_PREVIEW_CHARS = 400

#: Tools whose output the user waits to *see*. Each announces a typed skeleton
#: before it runs so the transcript reserves space with the right shape.
_PENDING_ARTIFACT_KIND = {
    "generate_visual": "chart",
    "generate_deck": "document",
    "generate_3d": "visual",
    "create_diagram": "diagram",
    "create_simulation": "simulation",
    "create_animation": "animation",
    "render_custom": "visual",
    "run_analysis": "analysis",
}


def _artifacts_from_events(events: list[dict]) -> list[dict]:
    """The artifacts the client was actually shown, in the order it saw them.

    Derived from the emitted events rather than re-walked from `tool_events`
    for one reason that matters: an artifact that FAILED verification was never
    emitted, and re-collecting from tool results would put it back — the exact
    broken output the gate exists to withhold would reappear on reload.

    It also preserves what the gate attached (`preview`, `verified`, `defects`),
    which the tool result does not carry.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for ev in events:
        if ev.get("event") != "artifact":
            continue
        data = ev.get("data") or {}
        url = str(data.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(dict(data))
    return out


def _step_timeline(events: list[dict]) -> list[dict]:
    """Rebuild the tool-step timeline from the events the client was sent.

    Derived from `progress_events` rather than assembled separately on purpose:
    anything the UI rendered live is, by construction, in that list, so the
    replayed transcript cannot drift from the streamed one as new event types
    are added.

    `name` is kept on every entry because the stats endpoint counts tool usage
    from this column.
    """
    steps: list[dict] = []
    by_id: dict[str, dict] = {}
    current: dict | None = None

    for ev in events:
        kind = ev.get("event")
        data = ev.get("data") or {}

        if kind == "step_start":
            step = {
                "id": data.get("id"),
                "name": data.get("tool"),        # stats reads this key
                "tool": data.get("tool"),
                "title": data.get("title", ""),
                "args": data.get("args") or {},
                "state": "running",
                "status": "",
                "summary": "",
                "detail": "",
                "substeps": [],
                "artifacts": [],
            }
            steps.append(step)
            if step["id"]:
                by_id[str(step["id"])] = step
            current = step

        elif kind == "step_note":
            target = by_id.get(str(data.get("id"))) or current
            if target and data.get("title"):
                target["title"] = data["title"]

        elif kind == "step_sub":
            target = by_id.get(str(data.get("id"))) or current
            if target:
                for prior in target["substeps"]:
                    if prior.get("state") == "running":
                        prior["state"] = "done"
                target["substeps"].append({
                    "text": data.get("text", ""),
                    "url": data.get("url", ""),
                    "detail": data.get("detail", ""),
                    "state": "running",
                })

        elif kind == "verify_end":
            # Keep the verdict on the step so a reloaded transcript still shows
            # that the artifact was opened and what the browser reported. A
            # "verified" badge that vanishes on refresh teaches the user not to
            # trust it.
            target = by_id.get(str(data.get("id"))) or current
            if target and data.get("checked"):
                target["verification"] = {
                    "ok": bool(data.get("ok")),
                    "attempt": data.get("attempt"),
                    "errors": data.get("errors") or [],
                    "warnings": data.get("warnings") or [],
                    "summary": data.get("summary", ""),
                }

        elif kind == "step_end":
            target = by_id.get(str(data.get("id"))) or current
            if target:
                status = data.get("status", "ok")
                target["status"] = status
                target["state"] = "error" if status in {"error", "rejected"} else "done"
                target["summary"] = data.get("summary", "")
                target["detail"] = data.get("detail", "")
                if data.get("error"):
                    target["error"] = data["error"]
                for sub in target["substeps"]:
                    sub["state"] = "done"
            current = None

        elif kind == "artifact" and current is not None:
            # Mirrors the live client, which records an artifact on the open step
            # AND renders it inline. Keeping both means history looks the same.
            current["artifacts"].append(data)

    # A turn cancelled mid-tool leaves a step open; close it so the replayed
    # panel does not spin forever.
    for step in steps:
        if step["state"] == "running":
            step["state"] = "done"
            step["status"] = step["status"] or "ok"
        for sub in step["substeps"]:
            sub["state"] = "done"
    return steps


def _preview_args(args: dict) -> dict:
    """Shrink tool arguments to something safe to ship to the client.

    Arguments feed the deterministic step title, so the client needs the shape
    (query text, slide count, code length) but never the full payload — a
    `run_analysis` script or a Vega spec would otherwise bloat every SSE frame.
    """
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, str):
            out[k] = v if len(v) <= _ARG_PREVIEW_CHARS else v[:_ARG_PREVIEW_CHARS] + "…"
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, list):
            # Length is what titles use ("12 slides"); contents are not needed.
            out[k] = [{} for _ in v[:200]]
        elif isinstance(v, dict):
            out[k] = {
                kk: (vv if isinstance(vv, (int, float, bool)) else str(vv)[:120])
                for kk, vv in list(v.items())[:8]
                if kk in {"title", "description", "kind", "name", "topic"}
            }
        else:
            out[k] = str(v)[:120]
    return out


def _detail(name: str, tool_input: dict, result: dict) -> str:
    """A compact, human-readable record of one tool execution.

    Shown inside the expanded step. Deliberately plain text rather than raw
    JSON: the reader is a student auditing what the assistant did, not a
    developer reading a trace.
    """
    if not isinstance(result, dict):
        return ""
    lines: list[str] = []

    if name == "run_analysis":
        code = str(tool_input.get("code") or "")
        if code:
            lines.append(code.strip()[:2000])
        out = (result.get("stdout") or "").strip()
        err = (result.get("stderr") or "").strip()
        if out:
            lines.append("--- output ---\n" + out[:4000])
        if err:
            lines.append("--- errors ---\n" + err[:2000])
    elif name in {"web_search", "search_library"}:
        for r in (result.get("results") or [])[:8]:
            title = r.get("title") or r.get("url") or ""
            url = r.get("url") or ""
            lines.append(f"• {str(title)[:110]}" + (f"\n  {url}" if url else ""))
    elif name == "deep_research":
        for q in (result.get("queries") or [])[:6]:
            lines.append(f"searched: {str(q)[:110]}")
        for p in (result.get("passages") or [])[:6]:
            lines.append(f"• {str(p.get('title') or p.get('url') or '')[:110]}")
    elif name == "query_warehouse":
        lines.append(str(tool_input.get("sql") or "")[:1000])
        rows = result.get("rows")
        if isinstance(rows, list):
            lines.append(f"--- {len(rows)} rows ---")
            for r in rows[:10]:
                lines.append(str(r)[:160])
    else:
        # Generic: what was asked for, and what came back.
        for k, v in (tool_input or {}).items():
            if k == "code":
                continue
            lines.append(f"{k}: {str(v)[:180]}")

    for f in (result.get("output_files") or [])[:10]:
        lines.append(f"→ {f.get('name')} ({f.get('mime')}, {f.get('bytes', 0)} bytes)")

    if result.get("error"):
        lines.append("error: " + str(result["error"])[:400])

    return "\n".join(lines)[:8000]


def _summarise(name: str, result: dict) -> str:
    """One-line outcome for a collapsed step chip."""
    if not isinstance(result, dict):
        return ""
    status = result.get("status")
    if status == "needs_repair":
        v = result.get("verification") or {}
        n = len(v.get("errors") or [])
        return (f"broken · {n} error{'s' if n != 1 else ''} · "
                f"repairing ({v.get('attempt', 1)}/{v.get('attempt', 1) + max(0, v.get('attempts_remaining', 0))})")
    if status and status not in {"ok", "success"}:
        return str(status)
    verification = result.get("verification")
    if isinstance(verification, dict) and verification.get("ran"):
        if verification.get("ok"):
            files = len(result.get("output_files") or [])
            return "verified · renders clean" + (f" · {files} files" if files > 1 else "")
        return f"released with {len(verification.get('errors') or [])} known defects"
    if name == "web_search":
        n = len(result.get("results") or [])
        return f"{n} results" if n else ""
    if name == "deep_research":
        n = result.get("pages_read") or len(result.get("passages") or [])
        return f"{n} pages" if n else ""
    if name == "search_library":
        n = len(result.get("results") or [])
        return f"{n} sources" if n else ""
    files = len(result.get("output_files") or [])
    if name == "run_analysis":
        ms = result.get("execution_time_ms") or 0
        bits = []
        if files:
            bits.append(f"{files} outputs")
        if ms:
            bits.append(f"{round(ms / 100) / 10}s")
        return " · ".join(bits)
    return f"{files} files" if files else ""


def _stream_tokens(text: str):
    """Yield the answer in small pieces (word-by-word, keeping newlines) so the
    client can render it fluidly. Markdown structure is preserved because we split
    on spaces only and keep '\\n' inside the tokens."""
    if not text:
        return
    # split keeping whitespace so markdown line structure is preserved
    import re as _re
    for tok in _re.findall(r"\S+\s*", text):
        yield tok
