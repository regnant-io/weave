"""Chat routes (architecture 5.2): POST a message, receive an SSE stream
(architecture 4.1 / 3 step 6). A non-streaming mode is also provided for
clients/tests that don't consume SSE."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import enforce_chat_limit, get_current_user
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
                            effort=body.effort, model=body.model, thread_id=body.thread_id)
        return MessageOut.model_validate(msg)

    def event_stream():
        try:
            for ev in orch.stream_turn(db, project, body.content, body.language,
                                       body.dataset_id, effort=body.effort, model=body.model,
                                       regenerate=body.regenerate,
                                       services_pref=body.services,
                                       thread_id=body.thread_id):
                yield _sse(ev["event"], ev["data"])
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


@router.post("/turns/{turn_id}/cancel")
def cancel_turn(turn_id: str, user: User = Depends(get_current_user)):
    """Stop a running turn. THE ONLY WAY A TURN IS STOPPED ON PURPOSE.

    It used to be implicit: closing the SSE connection fired a GeneratorExit
    that cancelled the run. That conflated two completely different events --
    "the user pressed Stop" and "the network dropped" -- and resolved both as
    cancellation, which is why a tunnel restart destroyed twenty minutes of
    work. Now that a dropped connection means nothing, stopping has to be
    something the client says explicitly, and this is where it says it.
    """
    from ..services.orchestration.live import get_turns

    live = get_turns().for_user(turn_id, str(user.id))
    if live is None:
        # Already finished, already reaped, or not this worker's turn. Nothing
        # to stop is not an error: the caller wanted it stopped and it is.
        return {"cancelled": False, "reason": "not running here"}
    live.cancel.set()
    return {"cancelled": True}


@router.get("/turns/{turn_id}/stream")
def resume_turn(
    turn_id: str,
    after: int = -1,
    user: User = Depends(get_current_user),
):
    """Reattach to a turn that is still running, from where the client left off.

    `after` is the sequence number of the last event the client actually
    received; events are replayed from the one after it. Defaulting to -1 (send
    everything) rather than 0 makes "I got nothing" and "I got event 0"
    distinguishable, which matters because replaying event 0 twice would print
    the opening of the answer twice.

    A turn this process does not know about is a 404, and that is the honest
    answer: the registry is in-process (see orchestration/live.py), so a
    reconnect routed to another worker cannot be served here. The client's
    fallback is to reload the thread, which for a finished turn shows the real
    answer.
    """
    orch = get_orchestrator()

    def event_stream():
        try:
            for ev in orch.resume_turn(turn_id, str(user.id), from_seq=after + 1):
                yield _sse(ev["event"], ev["data"])
        except LookupError:
            yield _sse("error", {
                "message": "that turn is no longer being tracked here",
                "code": "turn_not_live",
            })
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )
