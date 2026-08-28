"""Canvas tools — the assistant's half of the shared document.

The primitives are deliberately asymmetric to the human's. A person edits by
replacing the whole document from their editor; the assistant edits by ANCHOR —
find this text, replace it with that. Anchored edits rebase onto whatever the
document currently says, so the two can work at the same time without a
character-wise transform, and a genuine overlap surfaces as a failed anchor the
model can recover from rather than as a silently clobbered paragraph.

See models.Canvas for the full concurrency reasoning.
"""
from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry


def _svc(ctx: ToolContext):
    return ctx.services.get("canvas")


def _project_id(ctx: ToolContext) -> str:
    return str(getattr(ctx.project, "id", "") or "")


def _unavailable() -> dict:
    return {"status": "unavailable", "message": "the shared canvas is not available here"}


def _resolve(ctx: ToolContext, canvas_id: str = ""):
    """The named canvas, or the project's default (created on demand)."""
    svc = _svc(ctx)
    pid = _project_id(ctx)
    if canvas_id:
        return svc.get(ctx.db, pid, canvas_id)
    return svc.default(ctx.db, pid)


def _emit_change(ctx: ToolContext, canvas, summary: str) -> None:
    """Show the edit in the transcript as it happens.

    The socket already pushed the new text to anyone with the canvas open; this
    is what puts it in the CONVERSATION, so a user reading the chat sees that the
    document changed and why.
    """
    ctx.progress("canvas_update", {
        "canvas_id": canvas.id, "title": canvas.title,
        "revision": canvas.revision, "summary": summary,
        "chars": len(canvas.content or ""),
    })


def _read(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    canvas = _resolve(ctx, str(inp.get("canvas_id") or ""))
    if canvas is None:
        return {"status": "error", "error": "no such canvas in this project"}
    return {
        "status": "ok", "canvas_id": canvas.id, "title": canvas.title,
        "revision": canvas.revision, "updated_by": canvas.updated_by,
        "content": canvas.content or "",
        "chars": len(canvas.content or ""),
    }


def _list(ctx: ToolContext, _inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    rows = svc.list(ctx.db, _project_id(ctx))
    return {"status": "ok", "count": len(rows), "canvases": [
        {"canvas_id": c.id, "title": c.title, "revision": c.revision,
         "chars": len(c.content or ""), "updated_by": c.updated_by}
        for c in rows
    ]}


def _write(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    canvas = _resolve(ctx, str(inp.get("canvas_id") or ""))
    if canvas is None:
        return {"status": "error", "error": "no such canvas in this project"}
    content = str(inp.get("content") or "")
    if not content.strip():
        return {"status": "error", "error": "refusing to blank the document; "
                                            "use canvas_edit to remove a section"}
    updated = svc.write_assistant(ctx.db, canvas, content,
                                  summary=str(inp.get("summary") or "rewrote the document"))
    _emit_change(ctx, updated, "rewrote the document")
    return {"status": "ok", "canvas_id": updated.id, "revision": updated.revision,
            "chars": len(updated.content or "")}


def _edit(ctx: ToolContext, inp: dict) -> dict:
    from ..canvas import AnchorNotFound

    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    canvas = _resolve(ctx, str(inp.get("canvas_id") or ""))
    if canvas is None:
        return {"status": "error", "error": "no such canvas in this project"}
    try:
        updated, n = svc.edit_assistant(
            ctx.db, canvas, str(inp.get("find") or ""), str(inp.get("replace") or ""),
            replace_all=bool(inp.get("replace_all")),
        )
    except AnchorNotFound as exc:
        # Deliberately actionable: the model is told to re-read and retry, which
        # is the correct recovery when a human edited the same passage.
        return {"status": "error", "error": str(exc)}
    _emit_change(ctx, updated, f"edited {n} passage{'s' if n > 1 else ''}")
    return {"status": "ok", "canvas_id": updated.id, "revision": updated.revision,
            "replacements": n}


def _append(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    canvas = _resolve(ctx, str(inp.get("canvas_id") or ""))
    if canvas is None:
        return {"status": "error", "error": "no such canvas in this project"}
    text = str(inp.get("text") or "")
    if not text.strip():
        return {"status": "error", "error": "nothing to append"}
    updated = svc.append_assistant(ctx.db, canvas, text)
    _emit_change(ctx, updated, "appended a section")
    return {"status": "ok", "canvas_id": updated.id, "revision": updated.revision,
            "chars": len(updated.content or "")}


def _create(ctx: ToolContext, inp: dict) -> dict:
    svc = _svc(ctx)
    if svc is None:
        return _unavailable()
    try:
        canvas = svc.create(ctx.db, _project_id(ctx),
                            title=str(inp.get("title") or "Untitled"),
                            content=str(inp.get("content") or ""))
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    _emit_change(ctx, canvas, "created a document")
    return {"status": "ok", "canvas_id": canvas.id, "title": canvas.title,
            "revision": canvas.revision}


def register_canvas_tools(reg: ToolRegistry) -> None:
    common = {"trust_required": "verified", "requires_services": ("canvas",)}

    reg.register(Tool(
        name="canvas_read",
        description=(
            "Read the shared canvas — a document you and the user edit TOGETHER, "
            "live, in the side panel. Always read before editing: the user may "
            "have changed it since you last looked, and your edits are anchored "
            "to the text that is actually there. Omit canvas_id for the "
            "project's main document."
        ),
        input_schema={"type": "object", "properties": {
            "canvas_id": {"type": "string"}, "note": {"type": "string"},
        }},
        execute=_read, **common,
    ))

    reg.register(Tool(
        name="canvas_edit",
        description=(
            "Change part of the shared canvas by finding exact text and replacing "
            "it. THIS IS YOUR MAIN EDITING TOOL — prefer it over canvas_write for "
            "anything short of a full rewrite, because it leaves the rest of the "
            "document untouched while the user is working in it. Include enough "
            "surrounding text for `find` to be unique. If the anchor is gone the "
            "user has edited that passage: read the canvas again and retry."
        ),
        input_schema={"type": "object", "properties": {
            "find": {"type": "string", "description": "Exact text to replace."},
            "replace": {"type": "string", "description": "Replacement (empty to delete)."},
            "replace_all": {"type": "boolean"},
            "canvas_id": {"type": "string"}, "note": {"type": "string"},
        }, "required": ["find", "replace"]},
        execute=_edit, **common,
    ))

    reg.register(Tool(
        name="canvas_append",
        description=(
            "Add a new section to the end of the shared canvas. Use when you are "
            "extending the document rather than revising it — a new paragraph, a "
            "results section, another worked example."
        ),
        input_schema={"type": "object", "properties": {
            "text": {"type": "string"},
            "canvas_id": {"type": "string"}, "note": {"type": "string"},
        }, "required": ["text"]},
        execute=_append, **common,
    ))

    reg.register(Tool(
        name="canvas_write",
        description=(
            "Replace the ENTIRE contents of the shared canvas. Blunt: it discards "
            "whatever the user has typed since you last read it, so use it only "
            "for a genuine rewrite or to fill a document that is still empty. For "
            "everything else use canvas_edit."
        ),
        input_schema={"type": "object", "properties": {
            "content": {"type": "string"},
            "summary": {"type": "string", "description": "What changed, for the user."},
            "canvas_id": {"type": "string"}, "note": {"type": "string"},
        }, "required": ["content"]},
        execute=_write, **common,
    ))

    reg.register(Tool(
        name="canvas_create",
        description=(
            "Start a NEW shared document in this project, alongside the existing "
            "ones. Use when the work genuinely belongs in a separate document — a "
            "second chapter, a different deliverable — not as a way to avoid "
            "editing the current one."
        ),
        input_schema={"type": "object", "properties": {
            "title": {"type": "string"}, "content": {"type": "string"},
            "note": {"type": "string"},
        }, "required": ["title"]},
        execute=_create, **common,
    ))

    reg.register(Tool(
        name="canvas_list",
        description="List the shared documents in this project with their titles and sizes.",
        input_schema={"type": "object", "properties": {"note": {"type": "string"}}},
        execute=_list, **common,
    ))
