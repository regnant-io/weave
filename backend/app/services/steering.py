"""Redirecting a turn while it is still running.

THE PROBLEM
-----------
Watching a model work and being unable to say "no, not that" until it finishes is
the most frustrating way to use one. By the time the answer lands, the user has
spent a minute watching it go the wrong way, and their only option is to type the
correction and pay for the whole run again.

THE MECHANISM
-------------
Every turn registers itself here under its assistant-message id, which the client
already receives in the `meta` event before any tool runs. While the turn is
live, the client can POST a redirect. That does two things at once:

  1. it queues the text, and
  2. it sets an Event that the running generation treats as a cancel.

The orchestrator's generation call aborts promptly (the LLM engines already poll
a cancel object between tokens and between tool calls — see `SteerAwareCancel`
for how a steer is made to look like one), the queued redirect is appended to the
conversation as a real user turn, and generation restarts from there.

WHY RESTART RATHER THAN SPLICE
------------------------------
Tokens already streamed cannot be unsaid, and a model cannot be asked to change
its mind about text it has already committed to. Restarting with the redirect in
the history is the only approach that produces an answer genuinely shaped by it,
rather than one that contradicts its own opening paragraph. The client is told to
clear the partial answer (`answer_restart`), so what the user sees matches what
the model actually reasoned about.

The restart budget is small and deliberate: three per turn. Steering is meant to
be a nudge, not an interactive editing loop, and an unbounded budget lets a user
holding down a key keep one worker thread generating forever.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("weave.steering")

#: Restarts allowed per turn. Beyond this the redirects are still delivered —
#: they are appended to the conversation for the NEXT model call — but they stop
#: aborting the current generation, so the turn is guaranteed to terminate.
MAX_RESTARTS = 3

#: A turn nobody is watching any more should not hold a registration.
STALE_SECONDS = 60 * 60

MAX_TURNS = 512

#: Redirect text is a prompt fragment, so it is length-capped like any other.
MAX_STEER_CHARS = 2000


@dataclass
class SteerableTurn:
    turn_id: str
    user_id: str
    project_id: str
    #: Set when a redirect arrives; the generation loop reads it as a cancel.
    event: threading.Event = field(default_factory=threading.Event)
    queue: deque[dict] = field(default_factory=deque)
    restarts: int = 0
    created_at: float = field(default_factory=time.monotonic)
    #: Cleared when the turn finishes, so a late POST is rejected rather than
    #: silently dropped into a queue nobody will drain.
    live: bool = True


class SteerAwareCancel:
    """Makes a pending steer look like a cancellation to the LLM engines.

    The engines already check `cancel.is_set()` between streamed tokens and
    between tool calls — that is exactly the checkpoint density a redirect needs,
    and reusing it means no engine has to learn a second concept. The
    orchestrator distinguishes the two afterwards: a real cancel ends the turn, a
    steer restarts it.

    Duck-typed rather than a threading.Event subclass because Event is not
    designed to be subclassed and only `is_set` is ever called on it here.
    """

    def __init__(self, cancel: Any, steer: threading.Event) -> None:
        self._cancel = cancel
        self._steer = steer

    def is_set(self) -> bool:
        return bool(
            (self._cancel is not None and self._cancel.is_set()) or self._steer.is_set()
        )

    def set(self) -> None:  # pragma: no cover - present for interface parity
        if self._cancel is not None:
            self._cancel.set()

    @property
    def cancelled(self) -> bool:
        """True only for a REAL cancellation, so a steer is not mistaken for one."""
        return self._cancel is not None and self._cancel.is_set()


class SteeringBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: dict[str, SteerableTurn] = {}

    def _sweep(self) -> None:
        now = time.monotonic()
        for key in [k for k, t in self._turns.items()
                    if now - t.created_at > STALE_SECONDS or not t.live]:
            self._turns.pop(key, None)

    def register(self, *, turn_id: str, user_id: str, project_id: str) -> SteerableTurn:
        turn = SteerableTurn(turn_id=turn_id, user_id=user_id or "",
                             project_id=project_id or "")
        with self._lock:
            self._sweep()
            if len(self._turns) >= MAX_TURNS:
                oldest = min(self._turns.values(), key=lambda t: t.created_at)
                self._turns.pop(oldest.turn_id, None)
            self._turns[turn_id] = turn
        return turn

    def finish(self, turn_id: str) -> None:
        with self._lock:
            turn = self._turns.pop(turn_id, None)
        if turn is not None:
            turn.live = False

    def steer(self, turn_id: str, user_id: str, text: str, kind: str = "redirect") -> bool:
        """Queue a redirect and wake the generation. False if the turn is gone.

        Scoped to the owning user: holding a turn id must not be enough to inject
        a prompt fragment into somebody else's conversation.
        """
        text = (text or "").strip()[:MAX_STEER_CHARS]
        if not text:
            return False
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None or not turn.live:
                return False
            if turn.user_id and user_id and turn.user_id != user_id:
                return False
            turn.queue.append({"text": text, "kind": kind, "at": time.time()})
        # Only abort the running generation while there is restart budget. Past
        # it the redirect still lands in the queue and still reaches the model on
        # the next call — it just stops being able to restart this one, which is
        # what guarantees the turn terminates.
        if turn.restarts < MAX_RESTARTS:
            turn.event.set()
        return True

    def drain(self, turn_id: str) -> list[dict]:
        """Take everything queued for this turn and re-arm the event."""
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                return []
            items = list(turn.queue)
            turn.queue.clear()
            turn.event.clear()
        return items

    def pending(self, turn_id: str) -> bool:
        with self._lock:
            turn = self._turns.get(turn_id)
            return bool(turn and turn.queue)

    def note_restart(self, turn_id: str) -> int:
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                return MAX_RESTARTS
            turn.restarts += 1
            return turn.restarts

    def restarts_left(self, turn_id: str) -> int:
        with self._lock:
            turn = self._turns.get(turn_id)
            return MAX_RESTARTS - (turn.restarts if turn else MAX_RESTARTS)

    def get(self, turn_id: str) -> SteerableTurn | None:
        with self._lock:
            return self._turns.get(turn_id)

    def live_for(self, user_id: str) -> list[dict]:
        """Turns this user could steer — lets a reconnecting client re-attach."""
        with self._lock:
            return [
                {"turn_id": t.turn_id, "project_id": t.project_id,
                 "restarts_left": MAX_RESTARTS - t.restarts}
                for t in self._turns.values()
                if t.live and t.user_id == user_id
            ]


_broker: SteeringBroker | None = None


def get_steering() -> SteeringBroker:
    global _broker
    if _broker is None:
        _broker = SteeringBroker()
    return _broker
