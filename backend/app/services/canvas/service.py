"""The collaborative canvas: one document, two editors, live.

See `models.Canvas` for the concurrency model — server-authoritative revisions,
whole-document writes from the human (rejected when stale), anchored edits from
the assistant (rebased onto whatever the document currently says).

This module owns the write path and the fan-out. Every accepted write bumps the
revision and is broadcast to whoever has the document open, so the other party
sees it land rather than discovering it on reload.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ...models import Canvas

log = logging.getLogger("weave.canvas")

MAX_CONTENT_CHARS = 400_000
MAX_CANVASES_PER_PROJECT = 40


class CanvasConflict(Exception):
    """A whole-document write built on a revision that is no longer current."""

    def __init__(self, canvas: Canvas) -> None:
        super().__init__("the document changed while you were editing it")
        self.canvas = canvas


class AnchorNotFound(Exception):
    """An anchored edit whose `find` text is no longer in the document."""


class _Hub:
    """Fan-out to everyone watching a canvas.

    Subscribers are asyncio queues owned by WebSocket handlers, but writes
    arrive from BOTH the async request path and the orchestrator's worker
    THREAD (tool calls run off the event loop). So publishing has to be callable
    from a thread with no running loop, which is why the loop is captured when a
    subscriber registers and every put goes through `call_soon_threadsafe`.
    Getting this wrong means canvas edits made by the assistant never reach the
    browser — the exact case this feature exists for.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = (
            defaultdict(list)
        )

    def subscribe(self, canvas_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subs[canvas_id].append((loop, queue))
        return queue

    def unsubscribe(self, canvas_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subs[canvas_id] = [
                (loop, q) for (loop, q) in self._subs[canvas_id] if q is not queue
            ]
            if not self._subs[canvas_id]:
                self._subs.pop(canvas_id, None)

    def publish(self, canvas_id: str, payload: dict) -> None:
        with self._lock:
            targets = list(self._subs.get(canvas_id, ()))
        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except (RuntimeError, asyncio.QueueFull):
                # A closed loop or a subscriber that stopped draining must not
                # break the write for everyone else.
                continue

    def watchers(self, canvas_id: str) -> int:
        with self._lock:
            return len(self._subs.get(canvas_id, ()))


class CanvasService:
    def __init__(self) -> None:
        self.hub = _Hub()

    # -- reads -------------------------------------------------------------
    def list(self, db: Session, project_id: str) -> list[Canvas]:
        return (
            db.query(Canvas)
            .filter(Canvas.project_id == project_id)
            .order_by(Canvas.updated_at.desc())
            .all()
        )

    def get(self, db: Session, project_id: str, canvas_id: str) -> Canvas | None:
        return (
            db.query(Canvas)
            .filter(Canvas.id == canvas_id, Canvas.project_id == project_id)
            .first()
        )

    def default(self, db: Session, project_id: str) -> Canvas:
        """The project's canvas, created on demand.

        The common case is one shared document per project, and requiring an
        explicit create step before the assistant can write anything would make
        every first use a two-call dance.
        """
        existing = (
            db.query(Canvas)
            .filter(Canvas.project_id == project_id)
            .order_by(Canvas.updated_at.desc())
            .first()
        )
        if existing is not None:
            return existing
        return self.create(db, project_id, title="Shared canvas")

    def create(self, db: Session, project_id: str, title: str = "Untitled",
               content: str = "") -> Canvas:
        count = db.query(Canvas).filter(Canvas.project_id == project_id).count()
        if count >= MAX_CANVASES_PER_PROJECT:
            raise ValueError(f"a project may hold at most {MAX_CANVASES_PER_PROJECT} canvases")
        canvas = Canvas(project_id=project_id, title=(title or "Untitled")[:255],
                        content=content[:MAX_CONTENT_CHARS], revision=0,
                        updated_by="human")
        db.add(canvas)
        db.commit()
        db.refresh(canvas)
        return canvas

    # -- writes ------------------------------------------------------------
    def _commit(self, db: Session, canvas: Canvas, content: str, actor: str,
                *, summary: str) -> Canvas:
        canvas.content = content[:MAX_CONTENT_CHARS]
        canvas.revision = (canvas.revision or 0) + 1
        canvas.updated_by = actor
        canvas.updated_at = datetime.now(timezone.utc)
        db.add(canvas)
        db.commit()
        db.refresh(canvas)
        self.hub.publish(canvas.id, {
            "type": "update",
            "canvas_id": canvas.id,
            "revision": canvas.revision,
            "content": canvas.content,
            "title": canvas.title,
            "updated_by": actor,
            "summary": summary,
        })
        return canvas

    def write_human(self, db: Session, canvas: Canvas, content: str,
                    base_revision: int, title: str | None = None) -> Canvas:
        """Whole-document write from the editor. Rejects a stale base."""
        if int(base_revision) != int(canvas.revision or 0):
            raise CanvasConflict(canvas)
        if title is not None:
            canvas.title = title[:255] or canvas.title
        return self._commit(db, canvas, content, "human", summary="edited")

    def write_assistant(self, db: Session, canvas: Canvas, content: str,
                        summary: str = "rewrote the document") -> Canvas:
        """Whole-document write from the assistant.

        No base revision: the model was given the current text moments ago by
        `canvas_read`, and the tool description tells it to prefer anchored edits
        for anything short of a genuine rewrite. Wholesale replacement is the
        blunt instrument, and it is described as one.
        """
        return self._commit(db, canvas, content, "assistant", summary=summary)

    def edit_assistant(self, db: Session, canvas: Canvas, find: str, replace: str,
                       replace_all: bool = False) -> tuple[Canvas, int]:
        """Anchored find/replace — the assistant's primary edit primitive.

        Rebases by construction: it is applied to whatever the document says
        right now, so a human editing a different paragraph in the meantime is
        not a conflict at all. If the anchor is gone, the caller gets an error it
        can act on instead of a clobbered document.
        """
        current = canvas.content or ""
        if not find:
            raise AnchorNotFound("an empty `find` would match everywhere")
        occurrences = current.count(find)
        if occurrences == 0:
            raise AnchorNotFound(
                "the text to replace is not in the document — it may have been "
                "edited since you read it. Read the canvas again and retry."
            )
        if occurrences > 1 and not replace_all:
            raise AnchorNotFound(
                f"that text appears {occurrences} times, so replacing it is "
                f"ambiguous. Include more surrounding text to make it unique, or "
                f"set replace_all."
            )
        updated = current.replace(find, replace) if replace_all else current.replace(find, replace, 1)
        n = occurrences if replace_all else 1
        return self._commit(db, canvas, updated, "assistant",
                            summary=f"replaced {n} passage{'s' if n > 1 else ''}"), n

    def append_assistant(self, db: Session, canvas: Canvas, text: str) -> Canvas:
        current = canvas.content or ""
        joiner = "" if (not current or current.endswith("\n")) else "\n"
        return self._commit(db, canvas, current + joiner + text, "assistant",
                            summary="appended a section")

    def delete(self, db: Session, canvas: Canvas) -> None:
        canvas_id = canvas.id
        db.delete(canvas)
        db.commit()
        self.hub.publish(canvas_id, {"type": "deleted", "canvas_id": canvas_id})


_service: CanvasService | None = None


def get_canvas_service() -> CanvasService:
    global _service
    if _service is None:
        _service = CanvasService()
    return _service
