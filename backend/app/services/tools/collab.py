"""Tools that let the assistant talk to the user and to its own past.

`ask_user` — a mid-turn clarifying question. An agentic run often reaches a fork
only the user can settle (which dataset, which framing, which of two defensible
methods). Guessing wastes the whole run; abandoning the turn to ask throws away
the context already built. So the turn blocks on a real question and resumes
with the answer, exactly like any other tool call.

`remember` / `recall` — durable project memory. The rolling summary is a
fixed-length window over a growing conversation, so specifics fall out of it
precisely when they start to matter. These write small addressable entries that
every chat in the project reads back.
"""
from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry

#: An unanswered question must not pin a worker thread forever.
ASK_TIMEOUT_SECONDS = 15 * 60


def _ask_user(ctx: ToolContext, inp: dict) -> dict:
    from ..interaction import get_broker

    questions = _normalise_questions(inp)
    if not questions:
        return {"status": "error",
                "error": "provide at least one question with a `question` field"}

    user_id = str(getattr(getattr(ctx.project, "user", None), "id", "") or "")
    project_id = str(getattr(ctx.project, "id", "") or "")

    broker = get_broker()
    pending = broker.open(
        user_id=user_id,
        project_id=project_id,
        payload={
            "questions": questions,
            "thread_id": getattr(ctx.thread, "id", None),
            "message_id": ctx.message_id,
        },
    )

    # The client renders selectable cards from this event and POSTs the answer
    # to /api/v1/interactions/{id}.
    ctx.progress("ask_user", {
        "id": pending.id,
        "questions": questions,
        "thread_id": getattr(ctx.thread, "id", None),
    })

    answer = broker.wait(pending, timeout=ASK_TIMEOUT_SECONDS, cancel=ctx.cancel)

    if answer is None:
        ctx.progress("ask_user_done", {"id": pending.id, "answered": False})
        if ctx.cancelled():
            return {"status": "cancelled", "message": "the user left before answering"}
        return {
            "status": "unanswered",
            "message": ("The user did not answer in time. Proceed with your own best "
                        "judgement and state the assumption you made."),
        }

    ctx.progress("ask_user_done", {"id": pending.id, "answered": True,
                                   "answers": answer.get("answers", {})})
    return {
        "status": "ok",
        "answers": answer.get("answers", {}),
        "notes": answer.get("notes", ""),
    }


def _normalise_questions(inp: dict) -> list[dict]:
    """Accept both a single question and a list, and clamp the shape.

    Small local models are inconsistent about which form they emit; rejecting
    one of them would make the tool unusable on exactly the models this product
    runs on.
    """
    raw = inp.get("questions")
    if raw is None and inp.get("question"):
        raw = [{
            "question": inp.get("question"),
            "header": inp.get("header", ""),
            "options": inp.get("options") or [],
            "multi_select": bool(inp.get("multi_select")),
        }]
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    out: list[dict] = []
    for q in raw[:4]:
        if isinstance(q, str):
            q = {"question": q}
        if not isinstance(q, dict):
            continue
        text = str(q.get("question") or q.get("text") or "").strip()
        if not text:
            continue
        options = []
        for opt in (q.get("options") or [])[:6]:
            if isinstance(opt, str):
                options.append({"label": opt[:120], "description": ""})
            elif isinstance(opt, dict):
                label = str(opt.get("label") or opt.get("value") or "").strip()
                if label:
                    options.append({
                        "label": label[:120],
                        "description": str(opt.get("description") or "")[:280],
                    })
        out.append({
            "question": text[:400],
            "header": str(q.get("header") or "")[:24],
            "options": options,
            "multi_select": bool(q.get("multi_select")),
        })
    return out


def _remember(ctx: ToolContext, inp: dict) -> dict:
    svc = ctx.services.get("memory")
    if svc is None or ctx.project is None:
        return {"status": "unavailable", "message": "project memory is not available"}
    key = str(inp.get("key") or "").strip()
    content = str(inp.get("content") or "").strip()
    if not key or not content:
        return {"status": "error", "error": "both `key` and `content` are required"}
    entry = svc.remember(
        ctx.db, ctx.project, ctx.thread,
        key=key, content=content,
        kind=str(inp.get("kind") or "fact"),
        importance=int(inp.get("importance") or 3),
    )
    ctx.db.commit()
    ctx.progress("step_sub", {"text": f"Remembered: {entry.key}"})
    return {"status": "ok", "key": entry.key, "kind": entry.kind,
            "importance": entry.importance}


def _recall(ctx: ToolContext, inp: dict) -> dict:
    svc = ctx.services.get("memory")
    if svc is None or ctx.project is None:
        return {"status": "unavailable", "message": "project memory is not available"}
    entries = svc.recall(ctx.db, ctx.project, str(inp.get("query") or ""), limit=25)
    return {
        "status": "ok",
        "entries": [
            {"key": e.key, "kind": e.kind, "content": e.content,
             "importance": e.importance,
             "updated_at": e.updated_at.isoformat() if e.updated_at else None}
            for e in entries
        ],
    }


def _forget(ctx: ToolContext, inp: dict) -> dict:
    svc = ctx.services.get("memory")
    if svc is None or ctx.project is None:
        return {"status": "unavailable", "message": "project memory is not available"}
    ok = svc.forget(ctx.db, ctx.project, str(inp.get("key") or ""))
    ctx.db.commit()
    return {"status": "ok", "removed": ok}


def register_collab_tools(reg: ToolRegistry) -> None:
    reg.register(Tool(
        name="ask_user",
        description=(
            "Ask the user a clarifying question and WAIT for their answer before "
            "continuing. Use this when a choice would materially change the work "
            "and you cannot settle it from the conversation — which dataset, which "
            "framing, which of two defensible methods, what to do about an "
            "ambiguous requirement. Always offer concrete options; the user picks "
            "one (or types their own). Do NOT use it for things you can decide "
            "yourself, for permission to continue, or more than once per fork — an "
            "unnecessary question is more annoying than a stated assumption."
        ),
        input_schema={"type": "object", "properties": {
            "questions": {
                "type": "array",
                "description": "1-4 questions to ask together.",
                "items": {"type": "object", "properties": {
                    "question": {"type": "string", "description": "The full question."},
                    "header": {"type": "string",
                               "description": "Very short label, max 12 chars, e.g. 'Dataset'."},
                    "options": {
                        "type": "array",
                        "description": "2-4 concrete choices. Put your recommendation first.",
                        "items": {"type": "object", "properties": {
                            "label": {"type": "string"},
                            "description": {"type": "string",
                                            "description": "What choosing this means."},
                        }},
                    },
                    "multi_select": {"type": "boolean",
                                     "description": "true if several options may be picked."},
                }},
            },
        }, "required": ["questions"]},
        execute=_ask_user,
        trust_required="anonymous",
        # Only offered when a live client can answer. In a WhatsApp or batch turn
        # a blocking question would simply hang until it timed out.
        requires_services=("interactive",),
    ))

    reg.register(Tool(
        name="remember",
        description=(
            "Save a fact to PROJECT memory so every chat in this project can use it "
            "later. Use for things that stay true beyond this conversation: the "
            "user's goal, a chosen method, a dataset quirk, an approach that was "
            "tried and rejected, a naming convention, a standing preference. Reuse "
            "the same `key` to correct an earlier entry rather than adding a second "
            "one. Do not store transient chatter."
        ),
        input_schema={"type": "object", "properties": {
            "key": {"type": "string",
                    "description": "Short stable slug, e.g. 'dataset-units' or 'writing-style'."},
            "content": {"type": "string", "description": "The fact, in one or two sentences."},
            "kind": {"type": "string",
                     "enum": ["fact", "decision", "preference", "finding", "question", "artifact"]},
            "importance": {"type": "integer",
                           "description": "1-5. Use 5 only for standing constraints."},
        }, "required": ["key", "content"]},
        execute=_remember, trust_required="anonymous", requires_services=("memory",),
    ))

    reg.register(Tool(
        name="recall",
        description=(
            "Search this project's memory, including what was established in OTHER "
            "chats. The most important entries are already in your context; use "
            "this when you need something specific that is not there."
        ),
        input_schema={"type": "object", "properties": {
            "query": {"type": "string", "description": "Words to match; omit for everything."},
        }},
        execute=_recall, trust_required="anonymous", requires_services=("memory",),
    ))

    reg.register(Tool(
        name="forget",
        description="Remove a project-memory entry by key, when it is wrong or obsolete.",
        input_schema={"type": "object", "properties": {
            "key": {"type": "string"}}, "required": ["key"]},
        execute=_forget, trust_required="anonymous", requires_services=("memory",),
    ))
