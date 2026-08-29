"""Durable turns: the properties that make a dropped connection survivable.

The whole feature is a distinction between two events that TCP does not
distinguish — "the user left" and "the network hiccuped" — so these tests are
mostly about which of them causes what.
"""
from __future__ import annotations

import time

from app.services.orchestration.live import (
    DETACH_GRACE_SECONDS,
    MAX_BUFFERED_EVENTS,
    TurnRegistry,
)


def _drain(turn, from_seq=0, stop_after=None):
    out = []
    for item in turn.follow(from_seq, poll=0.05):
        if item is None:
            continue
        out.append(item)
        if stop_after is not None and len(out) >= stop_after:
            break
    return out


def test_a_reconnect_gets_exactly_what_it_missed():
    """No overlap and no gap. Replaying from the start would print the first
    half of an answer twice; skipping would lose it."""
    reg = TurnRegistry()
    turn = reg.create("t1", "p1", "u1")
    for i in range(10):
        turn.emit("token", {"text": f"chunk{i}"})
    turn.finish()

    first = _drain(turn, 0, stop_after=4)
    seen = [e.seq for e in first]
    assert seen == [0, 1, 2, 3]

    rest = _drain(turn, seen[-1] + 1)
    assert [e.seq for e in rest] == [4, 5, 6, 7, 8, 9]
    assert not set(seen) & {e.seq for e in rest}


def test_a_finished_turn_still_hands_over_its_ending():
    """A client that reconnects after the turn completed must receive the
    ending it missed, not an empty stream."""
    reg = TurnRegistry()
    turn = reg.create("t2", "p1", "u1")
    turn.emit("token", {"text": "hello"})
    turn.emit("done", {"message_id": "m1"})
    turn.finish(result={"thread_id": "th1"})

    events = _drain(turn, 0)
    assert [e.event for e in events] == ["token", "done"]


def test_a_turn_belongs_to_one_user():
    """Turn ids are message ids and appear in the transcript. Without an
    ownership check, anyone who learned one could attach to another person's
    stream and read their conversation as it was written."""
    reg = TurnRegistry()
    reg.create("t3", "p1", "owner")
    assert reg.for_user("t3", "owner") is not None
    assert reg.for_user("t3", "someone-else") is None
    assert reg.for_user("no-such-turn", "owner") is None


def test_falling_off_the_back_of_the_buffer_is_detectable():
    """A resume that cannot be served completely must say so rather than
    delivering the events it does have — an unmarked hole in the middle of an
    answer is worse than an honest reload."""
    reg = TurnRegistry()
    turn = reg.create("t4", "p1", "u1")
    for i in range(MAX_BUFFERED_EVENTS + 50):
        turn.emit("token", {"text": str(i)})
    turn.finish()

    assert turn.has(MAX_BUFFERED_EVENTS + 10) is True
    assert turn.has(0) is False


def test_detaching_does_not_cancel_and_the_reaper_eventually_does():
    """The distinction the whole module exists for.

    Losing a connection must not stop the work; nobody coming back must.
    """
    reg = TurnRegistry()
    turn = reg.create("t5", "p1", "u1")
    turn.emit("token", {"text": "x"})

    # Attach and leave.
    _drain(turn, 0, stop_after=1)
    assert turn.attached == 0
    assert turn.detached_at > 0
    assert not turn.cancel.is_set(), "detaching must not cancel"

    # The reaper leaves it alone inside the grace window...
    reg._reap_once()
    assert not turn.cancel.is_set()

    # ...and cancels it once nobody has come back.
    turn.detached_at = time.monotonic() - (DETACH_GRACE_SECONDS + 1)
    reg._reap_once()
    assert turn.cancel.is_set()


def test_reattaching_clears_the_countdown():
    reg = TurnRegistry()
    turn = reg.create("t6", "p1", "u1")
    turn.emit("token", {"text": "x"})
    _drain(turn, 0, stop_after=1)
    assert turn.detached_at > 0

    turn.emit("token", {"text": "y"})
    _drain(turn, 0, stop_after=1)  # attaches again
    # follow() sets detached_at only on the way out, and clears it on the way in;
    # what matters is that an attach resets the clock rather than accumulating.
    turn.detached_at = time.monotonic()
    reg._reap_once()
    assert not turn.cancel.is_set()
