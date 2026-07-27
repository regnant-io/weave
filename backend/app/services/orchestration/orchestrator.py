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
from ..render import get_render
from ..retrieval import get_retrieval_service
from ..tools import ToolContext, get_registry
from ..warehouse import get_warehouse
from ..websearch import get_web_search
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

    # -- public: non-streaming ----------------------------------------------

    def run_turn(
        self, db: Session, project: Project, user_text: str, language: str,
        dataset_id: str | None = None, effort: str | None = None, model: str | None = None,
    ) -> Message:
        assistant_msg, _ = self._process(db, project, user_text, language, dataset_id,
                                         effort=effort, model=model)
        return assistant_msg

    # -- public: streaming (SSE) --------------------------------------------

    def stream_turn(
        self, db: Session, project: Project, user_text: str, language: str,
        dataset_id: str | None = None, effort: str | None = None, model: str | None = None,
        regenerate: bool = False, services_pref: dict | None = None,
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
            q.put({"event": event, "data": data})

        def worker() -> None:
            try:
                msg, meta = self._process(db, project, user_text, language, dataset_id,
                                          emit=emit, effort=effort, model=model,
                                          cancel=cancel, regenerate=regenerate,
                                          services_pref=services_pref)
                holder["msg"] = msg
                holder["meta"] = meta
            except Exception as exc:  # noqa: BLE001
                holder["error"] = str(exc)
            finally:
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
            yield {"event": "done", "data": {"message_id": holder.get("msg").id if holder.get("msg") else None}}
        except GeneratorExit:
            # client disconnected (Stop) — signal the worker to abort promptly
            cancel.set()
            raise

    # -- core ----------------------------------------------------------------

    def _process(
        self, db: Session, project: Project, user_text: str, language: str,
        dataset_id: str | None, emit=None, effort: str | None = None, model: str | None = None,
        cancel=None, regenerate: bool = False, services_pref: dict | None = None,
    ) -> tuple[Message, dict]:
        engine = get_engine()

        # 1. persist the user's message. On regenerate we reuse the last user turn
        # and drop the previous assistant answer instead of duplicating.
        if regenerate:
            last_user = (
                db.query(Message).filter(Message.project_id == project.id, Message.role == "user")
                .order_by(Message.created_at.desc()).first()
            )
            last_asst = (
                db.query(Message).filter(Message.project_id == project.id, Message.role == "assistant")
                .order_by(Message.created_at.desc()).first()
            )
            if last_asst:
                db.delete(last_asst)
                db.commit()
            user_msg = last_user or self._store_message(db, project, "user", user_text, language, engine)
            user_text = user_msg.content_en or user_msg.content_sw or user_text
        else:
            user_msg = self._store_message(db, project, "user", user_text, language, engine)

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
            project_id=project.id, role="assistant",
            content_sw="", content_en="", original_language=language,
            tool_calls=[], citations=[],
        )
        db.add(assistant_msg)
        db.flush()

        # -- capability bus: registry + per-turn context ----------------------
        trust = getattr(getattr(project, "user", None), "trust_tier", "verified") or "verified"
        services = {"analysis": self.analysis, "retrieval": self.retrieval}
        web = get_web_search()
        if web.enabled:
            services["websearch"] = web
        render = get_render()
        if render.enabled:
            services["render"] = render
        warehouse = get_warehouse()
        if warehouse.enabled:
            services["warehouse"] = warehouse

        progress_events: list[dict] = []

        def _emit(event: str, data: dict) -> None:
            # Live sink (SSE) when streaming; always also collected for run_turn/meta.
            progress_events.append({"event": event, "data": data})
            if emit is not None:
                emit(event, data)

        ctx = ToolContext(
            db=db, project=project, dataset=dataset, message_id=assistant_msg.id,
            language=language, trust=trust, services=services, emit=_emit,
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
                       "mode": project.mode, "effort": (effort or "weave")})

        tool_events: list[dict] = []
        from ...config import settings as _s
        _counts = {"sandbox": 0, "web": 0}
        _web_tools = {"web_search", "deep_research"}

        _step_seq = {"n": 0}

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

            result = registry.execute(name, ctx, tool_input)

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
        if getattr(engine, "available", False):
            system = self._system_prompt(project, language, passages, dataset_profile, integrity, effort)
            messages = self._history_as_messages(db, project, language, up_to=user_msg)
            try:
                _emit("answer_start", {})
                result: TurnResult = engine.generate(
                    system=system, messages=messages, tools=tool_schemas,
                    tool_executor=tool_executor, tier=route.tier,
                    on_event=_emit, effort=effort, model=model, cancel=cancel,
                )
                answer = result.text
                tool_events = result.tool_events
                tier_used = result.tier_used
                engine_streamed = getattr(engine, "name", "") == "ollama"
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
        artifacts = self._collect_artifacts(tool_events)
        images = self._collect_web_images(tool_events, passages)
        assistant_msg.citations = citations
        assistant_msg.tool_calls = [
            {"name": e.get("name"), "status": e.get("result", {}).get("status"),
             "output_files": e.get("result", {}).get("output_files", [])}
            for e in tool_events
        ]
        # persist artifacts + images on the message so history re-renders them
        assistant_msg.artifacts = artifacts
        assistant_msg.images = images
        db.add(assistant_msg)

        # 10. rolling project summary (architecture 6.2 project-memory layer)
        self._update_summary(project, user_text, answer)
        db.add(project)
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

        meta = {
            "intent": route.intent, "tier": tier_used, "grounded": grounded,
            "grounding_note": grounding_note if not grounded else "",
            "tool_events": tool_events, "progress": progress_events,
            "artifacts": artifacts, "images": images,
        }
        return assistant_msg, meta

    def _collect_artifacts(self, tool_events: list[dict]) -> list[dict]:
        """Turn tool output_files (charts/decks/PDFs/3D) into renderable artifact
        references with a frontend-proxied URL."""
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
                       effort=None) -> str:
        from ...runtime import effort_spec
        base = prompts.assemble_system_prompt(
            mode=project.mode, language=language, passages=passages,
            project_summary=project.summary, hypotheses=project.hypotheses or [],
            dataset_profile=dataset_profile,
        )
        base += "\n\n" + effort_spec(effort)["prompt"]
        if integrity:
            base += "\n\n" + guardrails.integrity_redirect_instruction(language)
        return base

    def _history_as_messages(self, db, project, language, up_to: Message) -> list[dict]:
        msgs = (
            db.query(Message)
            .filter(Message.project_id == project.id)
            .order_by(Message.created_at)
            .all()
        )
        out: list[dict] = []
        for m in msgs[-12:]:
            if m.role not in {"user", "assistant"}:
                continue
            content = m.content_sw if language == "sw" else m.content_en
            if not content.strip():
                continue
            out.append({"role": m.role, "content": content})
        # ensure the just-stored user message is last
        if not out or out[-1]["role"] != "user":
            out.append({"role": "user", "content": up_to.content_sw if language == "sw" else up_to.content_en})
        return out

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

    def _store_message(self, db, project, role, text, language, engine) -> Message:
        # A user's own words are never machine-translated for storage — the literal
        # text is kept in both columns so the bilingual toggle always shows exactly
        # what they typed. (Assistant answers ARE translated, in _process.)
        content_sw = content_en = text
        msg = Message(
            project_id=project.id, role=role, original_language=language,
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
    if status and status not in {"ok", "success"}:
        return str(status)
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
