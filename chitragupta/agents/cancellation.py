"""Stopping a turn that has already started.

Stop used to abort the browser's fetch and print "stopped". The server never
heard about it: a High-effort turn stopped at round three carried on for up to
twenty-one more model calls and then spent two more learning from a
conversation the user had walked away from — all on the user's own key. The app
said the work had ended and the bill said otherwise, which is the shape
`/CLAUDE.md` names as a lie.

So a turn has a name and an event, and the loop reads that event between
rounds, before each tool runs, and while a stream is still arriving. It stops at
whichever of those it reaches first, keeps whatever it had written, and says so.

**The client chooses the id.** A turn is cancellable from the moment the user
can see a Stop button, and a server-assigned id leaves a window at the start of
exactly the slowest turns where Stop would have nothing to name. As a
consequence `cancel()` may arrive before `begin()` — so it records the
cancellation rather than discarding it, and the turn that registers afterwards
finds an event that is already set and stops at its first check.
"""
from __future__ import annotations

import threading

#: Turns tracked at once. A browser that goes away mid-turn never calls `end`,
#: so this is bounded rather than trusted: far above any real number of
#: concurrent turns, low enough that a client looping on `cancel` with fresh ids
#: cannot grow it without limit.
MAX_TRACKED = 64

_lock = threading.Lock()
_turns: dict[str, threading.Event] = {}


def begin(turn_id: str | None) -> threading.Event | None:
    """Register a turn and return the event that stops it.

    `None` for a turn with no id — the caller then has nothing to cancel, which
    is the old behaviour and is still what an internal turn (a routine, a
    delegated question) gets when nobody is watching it.
    """
    if not turn_id:
        return None
    with _lock:
        existing = _turns.get(turn_id)
        if existing is not None:
            # Either a retry of the same turn, or a Stop that arrived first.
            return existing
        if len(_turns) >= MAX_TRACKED:
            for stale in list(_turns)[:len(_turns) - MAX_TRACKED + 1]:
                _turns.pop(stale, None)
        event = threading.Event()
        _turns[turn_id] = event
        return event


def cancel(turn_id: str) -> bool:
    """Ask the turn to stop. True once it is asked, whether or not it started.

    Idempotent on purpose: pressing Stop twice is not an error, and a Stop that
    lands before the turn registers is recorded for it rather than lost.
    """
    if not turn_id:
        return False
    with _lock:
        event = _turns.get(turn_id)
        if event is None:
            if len(_turns) >= MAX_TRACKED:
                for stale in list(_turns)[:len(_turns) - MAX_TRACKED + 1]:
                    _turns.pop(stale, None)
            event = threading.Event()
            _turns[turn_id] = event
        event.set()
    return True


def end(turn_id: str | None) -> None:
    """Forget a turn. Called on every exit path, including a failure."""
    if not turn_id:
        return
    with _lock:
        _turns.pop(turn_id, None)


def stopped(event: threading.Event | None) -> bool:
    """Has this turn been asked to stop? Reads safely when there is no event."""
    return event is not None and event.is_set()


def tracked() -> int:
    """How many turns are registered. For tests and diagnostics."""
    with _lock:
        return len(_turns)
