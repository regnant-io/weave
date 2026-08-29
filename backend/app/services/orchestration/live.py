"""Live turns: a running turn that outlives the connection watching it.

THE PROBLEM

A turn was tied to the HTTP request that started it. The generator that produced
the SSE stream owned the queue, and when the client went away — a refresh, a
tunnel dropping, a phone switching from wifi to mobile data, a laptop lid — the
generator was closed, `GeneratorExit` fired, and the turn was cancelled.

For a chat reply that is a reasonable trade. For this product it is not. A
Tapestry run builds software, installs packages, runs tests and renders
artifacts; it can take many minutes, and the audience is on connections that
drop routinely. Losing twenty minutes of work to a network blip is bad on its
own, and worse than it looks: everything the turn had already done — files
written, packages installed, model quota spent — is gone with no record and no
way to ask for it back. Users learn not to start long jobs, which removes the
capability the product is built around.

WHAT THIS DOES INSTEAD

The turn is a first-class object with its own lifetime. It writes numbered
events into a buffer; connections ATTACH to it and read from wherever they left
off. A dropped connection detaches, the turn keeps working, and a reconnect
replays what was missed and then continues live. Cancellation becomes something
a user does deliberately, not something the network does to them.

A turn with nobody watching is still cancelled — after a grace period long
enough to reconnect through a bad handover, not the moment a socket closes. Two
different things are being distinguished that TCP does not distinguish for us:
"the user left" and "the network hiccuped".

SCOPE, HONESTLY

The registry is in-process. A reconnect that a load balancer routes to a
different worker will not find the turn, and gets a 404. That is a real limit
and it is a survivable one, because the turn is persisted when it finishes: the
client's fallback is to reload the thread, which shows the completed answer. The
alternative — every event through Redis — buys cross-worker resume at the cost
of putting a network round trip in the token path, and is not worth it until
sticky routing is genuinely impossible.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator

log = logging.getLogger("weave.live")

#: How long a turn keeps working with nobody attached before it is cancelled.
#:
#: Long enough to survive a wifi-to-mobile handover, a tunnel restart or a
#: fumbled page reload; short enough that closing the tab does not leave a model
#: generating for ten minutes at somebody's expense.
DETACH_GRACE_SECONDS = 90.0

#: How long a FINISHED turn's events are kept so a late reconnect can still
#: collect the ending it missed.
FINISHED_TTL_SECONDS = 300.0

#: Cap on buffered events per turn. A long run emits thousands of tokens; the
#: buffer is what makes resume possible, and it cannot be allowed to grow
#: without limit. Past this the OLDEST events are dropped, and a client
#: resuming from before the cut is told to reload rather than shown a hole.
MAX_BUFFERED_EVENTS = 20_000


@dataclass
class _Event:
    seq: int
    event: str
    data: dict


@dataclass
class LiveTurn:
    """One running turn, and everything watching it."""

    turn_id: str
    project_id: str
    user_id: str
    cancel: threading.Event = field(default_factory=threading.Event)

    _events: list[_Event] = field(default_factory=list)
    #: Sequence number of `_events[0]`. Non-zero once trimming has happened,
    #: which is how a resume request can tell it has fallen off the back.
    _base: int = 0
    _next_seq: int = 0
    _cv: threading.Condition = field(default_factory=threading.Condition)

    done: bool = False
    error: str = ""
    result: dict = field(default_factory=dict)

    attached: int = 0
    detached_at: float = 0.0
    finished_at: float = 0.0
    started_at: float = field(default_factory=time.monotonic)

    # -- producer side -----------------------------------------------------

    def emit(self, event: str, data: dict) -> None:
        with self._cv:
            self._events.append(_Event(self._next_seq, event, dict(data or {})))
            self._next_seq += 1
            if len(self._events) > MAX_BUFFERED_EVENTS:
                drop = len(self._events) - MAX_BUFFERED_EVENTS
                del self._events[:drop]
                self._base += drop
            self._cv.notify_all()

    def finish(self, *, error: str = "", result: dict | None = None) -> None:
        with self._cv:
            self.done = True
            self.error = error
            self.result = result or {}
            self.finished_at = time.monotonic()
            self._cv.notify_all()

    # -- consumer side -----------------------------------------------------

    @property
    def next_seq(self) -> int:
        with self._cv:
            return self._next_seq

    def has(self, from_seq: int) -> bool:
        """Whether everything from `from_seq` onward is still buffered."""
        with self._cv:
            return from_seq >= self._base

    def follow(self, from_seq: int = 0, *, poll: float = 10.0) -> Iterator[_Event | None]:
        """Yield events from `from_seq`, then block for new ones until done.

        Yields `None` on a poll timeout so the caller can send a keepalive —
        proxies and mobile networks close a connection that has been silent for
        thirty seconds, which would undo the whole point of this module.
        """
        with self._cv:
            self.attached += 1
            self.detached_at = 0.0
        try:
            cursor = max(from_seq, 0)
            while True:
                with self._cv:
                    cursor = max(cursor, self._base)
                    while cursor >= self._next_seq and not self.done:
                        if not self._cv.wait(timeout=poll):
                            yield None  # keepalive tick
                    if cursor >= self._next_seq and self.done:
                        return
                    batch = [e for e in self._events if e.seq >= cursor]
                for item in batch:
                    cursor = item.seq + 1
                    yield item
        finally:
            with self._cv:
                self.attached -= 1
                if self.attached <= 0:
                    self.detached_at = time.monotonic()


class TurnRegistry:
    """Every live turn in this process, and the reaper that ends them."""

    def __init__(self) -> None:
        self._turns: dict[str, LiveTurn] = {}
        self._lock = threading.Lock()
        self._reaper: threading.Thread | None = None

    def create(self, turn_id: str, project_id: str, user_id: str) -> LiveTurn:
        turn = LiveTurn(turn_id=turn_id, project_id=project_id, user_id=user_id)
        with self._lock:
            self._turns[turn_id] = turn
        self._ensure_reaper()
        return turn

    def get(self, turn_id: str) -> LiveTurn | None:
        with self._lock:
            return self._turns.get(turn_id)

    def for_user(self, turn_id: str, user_id: str) -> LiveTurn | None:
        """A turn, but only for the person whose turn it is.

        Resume is addressed by turn id, and a turn id is a message id that
        appears in the transcript — so without this check anyone who learned one
        could attach to another person's stream and read their conversation as
        it was written. Ownership is checked here rather than at the route so it
        cannot be forgotten by a second caller.
        """
        turn = self.get(turn_id)
        if turn is None:
            return None
        if user_id and turn.user_id and turn.user_id != user_id:
            return None
        return turn

    def cancel(self, turn_id: str) -> bool:
        turn = self.get(turn_id)
        if turn is None:
            return False
        turn.cancel.set()
        return True

    def drop(self, turn_id: str) -> None:
        with self._lock:
            self._turns.pop(turn_id, None)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._turns.values() if not t.done)

    # -- reaping -----------------------------------------------------------

    def _ensure_reaper(self) -> None:
        if self._reaper is not None and self._reaper.is_alive():
            return
        self._reaper = threading.Thread(target=self._reap_loop, daemon=True,
                                        name="weave-turn-reaper")
        self._reaper.start()

    def _reap_loop(self) -> None:
        while True:
            time.sleep(5.0)
            try:
                self._reap_once()
            except Exception:  # noqa: BLE001 - the reaper must never die
                log.exception("turn reaper iteration failed")

    def _reap_once(self) -> None:
        now = time.monotonic()
        with self._lock:
            turns = list(self._turns.items())

        for turn_id, turn in turns:
            if turn.done:
                if turn.finished_at and now - turn.finished_at > FINISHED_TTL_SECONDS:
                    self.drop(turn_id)
                continue
            # Running, nobody watching, and nobody has come back.
            if turn.attached <= 0 and turn.detached_at:
                if now - turn.detached_at > DETACH_GRACE_SECONDS and not turn.cancel.is_set():
                    log.info("cancelling turn %s: nobody reattached in %.0fs",
                             turn_id, DETACH_GRACE_SECONDS)
                    turn.cancel.set()


_registry: TurnRegistry | None = None


def get_turns() -> TurnRegistry:
    global _registry
    if _registry is None:
        _registry = TurnRegistry()
    return _registry
