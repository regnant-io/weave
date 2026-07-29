"""Mid-turn questions from the assistant to the user.

An agentic turn sometimes reaches a fork only the user can resolve — which
dataset, which framing, which of two defensible methods. Guessing wastes a long
run; stopping and answering "I need to know X" throws away all the context the
model has built up and makes the user re-prompt.

So the turn BLOCKS instead. The tool emits an `ask_user` SSE event, parks the
worker thread on an Event, and the client POSTs the answer back to
`/api/v1/interactions/{id}`, which wakes it. From the model's point of view it
is an ordinary tool call that returns the user's answer.

Design constraints this has to respect:

  * The waiting thread must be interruptible. If the user closes the tab, the
    orchestrator's `cancel` Event fires and we must stop waiting — otherwise a
    worker thread leaks for the full timeout on every abandoned turn.
  * A pending question must expire. A user who never answers must not pin a
    thread forever, so there is a hard ceiling after which the tool returns
    "unanswered" and the model proceeds on its own judgement.
  * Answers are keyed by an unguessable id and scoped to the asking user, so one
    user cannot answer another's question.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("weave.interaction")

#: How long a question may stay unanswered before the model gives up and
#: proceeds. Long enough for someone to come back to their phone, short enough
#: that an abandoned turn eventually releases its worker.
DEFAULT_TIMEOUT_SECONDS = 15 * 60

#: Cap so a runaway loop can't accumulate pending questions forever.
MAX_PENDING = 256


@dataclass
class PendingQuestion:
    id: str
    user_id: str
    project_id: str
    payload: dict
    event: threading.Event = field(default_factory=threading.Event)
    answer: dict | None = None
    created_at: float = field(default_factory=time.monotonic)


class InteractionBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, PendingQuestion] = {}

    def _sweep(self) -> None:
        """Drop questions nobody will ever answer. Called on every open()."""
        now = time.monotonic()
        stale = [
            k for k, q in self._pending.items()
            if now - q.created_at > DEFAULT_TIMEOUT_SECONDS * 2
        ]
        for k in stale:
            self._pending.pop(k, None)

    def open(self, *, user_id: str, project_id: str, payload: dict) -> PendingQuestion:
        q = PendingQuestion(
            id=secrets.token_urlsafe(16), user_id=user_id or "",
            project_id=project_id or "", payload=payload,
        )
        with self._lock:
            self._sweep()
            if len(self._pending) >= MAX_PENDING:
                # Evict the oldest rather than refusing: the newest question is
                # the one someone is actually looking at.
                oldest = min(self._pending.values(), key=lambda p: p.created_at)
                self._pending.pop(oldest.id, None)
            self._pending[q.id] = q
        return q

    def answer(self, question_id: str, user_id: str, answer: dict) -> bool:
        with self._lock:
            q = self._pending.get(question_id)
            # Scope the answer to the asking user: an id alone must not be
            # enough to inject a response into someone else's turn.
            if q is None or (q.user_id and user_id and q.user_id != user_id):
                return False
        q.answer = answer
        q.event.set()
        return True

    def wait(
        self, q: PendingQuestion, *, timeout: float, cancel: Any = None
    ) -> dict | None:
        """Block until answered, cancelled, or timed out.

        Polls in short slices rather than one long `wait(timeout)` so a client
        disconnect is noticed within a second instead of after fifteen minutes.
        """
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    return None
                if q.event.wait(timeout=0.5):
                    return q.answer
            return None
        finally:
            with self._lock:
                self._pending.pop(q.id, None)

    def get(self, question_id: str) -> PendingQuestion | None:
        with self._lock:
            return self._pending.get(question_id)

    def pending_for(self, user_id: str) -> list[dict]:
        """Open questions for a user — lets a reconnecting client re-render them."""
        with self._lock:
            return [
                {"id": q.id, "project_id": q.project_id, **q.payload}
                for q in self._pending.values()
                if q.user_id == user_id
            ]


_broker: InteractionBroker | None = None


def get_broker() -> InteractionBroker:
    global _broker
    if _broker is None:
        _broker = InteractionBroker()
    return _broker
