"""Chat routes (architecture 5.2): POST a message, receive an SSE stream
(architecture 4.1 / 3 step 6). A non-streaming mode is also provided for
clients/tests that don't consume SSE."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import enforce_chat_limit
from ..models import Project, User
from ..schemas import MessageCreate, MessageOut
from ..services.orchestration import get_orchestrator

router = APIRouter()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.delete("/projects/{project_id}/messages/from/{message_id}")
def truncate_from(project_id: str, message_id: str, db: Session = Depends(get_db),
                  user: User = Depends(enforce_chat_limit)):
    """Delete `message_id` and every message after it (used to edit-and-resend)."""
    from ..models import Message as M
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == user.id).first()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    anchor = db.query(M).filter(M.id == message_id, M.project_id == project_id).first()
    if not anchor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "message not found")
    victims = db.query(M).filter(M.project_id == project_id, M.created_at >= anchor.created_at).all()
    for m in victims:
        db.delete(m)
    db.commit()
    return {"deleted": len(victims)}


@router.post("/projects/{project_id}/messages")
def post_message(
    project_id: str,
    body: MessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(enforce_chat_limit),
):
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")

    orch = get_orchestrator()

    if not body.stream:
        msg = orch.run_turn(db, project, body.content, body.language, body.dataset_id,
                            effort=body.effort, model=body.model)
        return MessageOut.model_validate(msg)

    def event_stream():
        try:
            for ev in orch.stream_turn(db, project, body.content, body.language,
                                       body.dataset_id, effort=body.effort, model=body.model,
                                       regenerate=body.regenerate,
                                       services_pref=body.services):
                yield _sse(ev["event"], ev["data"])
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )
