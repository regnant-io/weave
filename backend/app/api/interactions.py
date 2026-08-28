"""Answering the assistant's mid-turn questions.

The `ask_user` tool parks the turn's worker thread on an Event; this endpoint is
what wakes it. Answers are scoped to the asking user inside the broker, so
holding a question id is not by itself enough to inject a response into someone
else's conversation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_current_user
from ..models import User
from ..schemas import InteractionAnswer
from ..services.interaction import get_broker

router = APIRouter()


@router.get("/interactions")
def list_pending(user: User = Depends(get_current_user)) -> dict:
    """Open questions for this user.

    A client that reconnects mid-turn (tab restored, flaky mobile link) would
    otherwise show a conversation stuck mid-thought with no way to answer.
    """
    return {"pending": get_broker().pending_for(user.id)}


@router.post("/interactions/{question_id}")
def answer(question_id: str, body: InteractionAnswer,
           user: User = Depends(get_current_user)) -> dict:
    ok = get_broker().answer(
        question_id, user.id,
        {"answers": body.answers or {}, "notes": body.notes or ""},
    )
    if not ok:
        # Expired, already answered, or not this user's question — all the same
        # to the caller, and saying which would leak the existence of an id.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "this question is no longer waiting for an answer",
        )
    return {"accepted": True}
