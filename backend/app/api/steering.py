"""Redirecting a turn while it is still running.

The client holds the turn id from the `meta` SSE event, which arrives before any
tool runs, so a redirect can be sent from the first second of a turn to its last.
See services/steering.py for why a redirect restarts generation rather than being
spliced into text the model has already committed to.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_current_user
from ..models import User
from ..schemas import SteerIn
from ..services.steering import get_steering

router = APIRouter()


@router.get("/steerable")
def steerable(user: User = Depends(get_current_user)) -> dict:
    """Turns this user could redirect right now.

    A client that reconnects mid-turn (tab restored, flaky mobile link) would
    otherwise show a conversation it cannot influence, with no way to tell
    whether steering is still possible.
    """
    return {"turns": get_steering().live_for(user.id)}


@router.post("/steer/{turn_id}")
def steer(turn_id: str, body: SteerIn, user: User = Depends(get_current_user)) -> dict:
    broker = get_steering()
    ok = broker.steer(turn_id, user.id, body.text, kind=body.kind or "redirect")
    if not ok:
        # Finished, never existed, or not this user's turn — all the same to the
        # caller, and distinguishing them would leak that an id exists.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "this turn is no longer running, so there is nothing to redirect",
        )
    return {"accepted": True, "restarts_left": broker.restarts_left(turn_id)}
