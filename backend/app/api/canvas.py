"""Canvas routes: read, write, and a live socket both parties watch.

The socket carries updates in one direction only — server to client. Human edits
go over HTTP PUT, because that is the path that has to be able to REJECT a write
built on a stale revision, and a fire-and-forget socket message cannot carry a
rejection back to the editor that sent it in a way it can reason about.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..deps import get_current_user
from ..models import Project, User
from ..schemas import CanvasOut, CanvasPatchIn
from ..security import decode_ws_ticket
from ..services.canvas import CanvasConflict, get_canvas_service

log = logging.getLogger("weave.canvas.api")
router = APIRouter()


def _owned(db: Session, project_id: str, user: User) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


@router.get("/projects/{project_id}/canvases", response_model=list[CanvasOut])
def list_canvases(project_id: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    _owned(db, project_id, user)
    svc = get_canvas_service()
    rows = svc.list(db, project_id)
    if not rows:
        # A project always has somewhere to write, so the client never has to
        # special-case an empty state before the first edit.
        rows = [svc.default(db, project_id)]
    return [CanvasOut.model_validate(c) for c in rows]


@router.post("/projects/{project_id}/canvases", response_model=CanvasOut, status_code=201)
def create_canvas(project_id: str, body: dict, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    _owned(db, project_id, user)
    try:
        canvas = get_canvas_service().create(
            db, project_id, title=str(body.get("title") or "Untitled"),
            content=str(body.get("content") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CanvasOut.model_validate(canvas)


@router.get("/projects/{project_id}/canvases/{canvas_id}", response_model=CanvasOut)
def read_canvas(project_id: str, canvas_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    _owned(db, project_id, user)
    canvas = get_canvas_service().get(db, project_id, canvas_id)
    if canvas is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canvas not found")
    return CanvasOut.model_validate(canvas)


@router.put("/projects/{project_id}/canvases/{canvas_id}", response_model=CanvasOut)
def write_canvas(project_id: str, canvas_id: str, body: CanvasPatchIn,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Whole-document write from the editor.

    409 when `base_revision` is stale, carrying the current document so the
    client can show the divergence rather than guessing. Overwriting instead
    would silently discard whatever the assistant (or another tab) just wrote.
    """
    _owned(db, project_id, user)
    svc = get_canvas_service()
    canvas = svc.get(db, project_id, canvas_id)
    if canvas is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canvas not found")
    try:
        updated = svc.write_human(db, canvas, body.content, body.base_revision, body.title)
    except CanvasConflict as conflict:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error": "the document changed while you were editing it",
                "current": CanvasOut.model_validate(conflict.canvas).model_dump(mode="json"),
            },
        ) from conflict
    return CanvasOut.model_validate(updated)


@router.delete("/projects/{project_id}/canvases/{canvas_id}")
def delete_canvas(project_id: str, canvas_id: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    _owned(db, project_id, user)
    svc = get_canvas_service()
    canvas = svc.get(db, project_id, canvas_id)
    if canvas is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "canvas not found")
    svc.delete(db, canvas)
    return {"deleted": True}


@router.websocket("/ws/canvas/{canvas_id}")
async def canvas_socket(websocket: WebSocket, canvas_id: str, token: str = ""):
    """Live updates for one canvas.

    Authenticated by a ticket in the query string: browsers cannot set headers on
    a WebSocket handshake, so there is nowhere else to put it. It is a
    socket-scoped, sixty-second credential rather than the session token — see
    `security.create_ws_ticket` for why that distinction matters when the value
    ends up in proxy logs.
    """
    user_id = _user_from_token(token)
    if not user_id:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        from ..models import Canvas
        canvas = db.query(Canvas).join(Project, Canvas.project_id == Project.id).filter(
            Canvas.id == canvas_id, Project.user_id == user_id
        ).first()
        if canvas is None:
            await websocket.close(code=4404)
            return
        snapshot = {
            "type": "snapshot", "canvas_id": canvas.id, "title": canvas.title,
            "content": canvas.content, "revision": canvas.revision,
            "updated_by": canvas.updated_by,
        }
    finally:
        db.close()

    await websocket.accept()
    svc = get_canvas_service()
    queue = svc.hub.subscribe(canvas_id)
    try:
        await websocket.send_json(snapshot)
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=25)
            except asyncio.TimeoutError:
                # Proxies close an idle socket. A keepalive is cheaper than the
                # reconnect storm that follows one being dropped mid-edit.
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.debug("canvas socket closed: %s", exc)
    finally:
        svc.hub.unsubscribe(canvas_id, queue)
        with contextlib.suppress(Exception):
            await websocket.close()


def _user_from_token(token: str) -> str | None:
    if not token:
        return None
    payload = decode_ws_ticket(token)
    return payload.get("sub") if isinstance(payload, dict) else None
