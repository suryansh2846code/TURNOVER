"""Work that follows a turn but must not delay it.

Two model calls used to run after the reply was finished and before the turn
returned: one extracting durable facts from what the user said, one curating
them into the canonical layer. Neither changes the answer. Both ran on the
critical path, so the text stopped arriving and then the user waited, with
nothing on screen explaining why — and a slow or failing extraction delayed an
answer that was already correct.

So they run here instead. The turn returns, and the brain catches up.

Deliberately a small fixed pool rather than a thread per turn: this work touches
SQLite and a provider, and the failure mode to design against is a user sending
ten messages quickly and getting ten extractions racing each other. Two at a
time is enough to keep up with a person typing.
"""
from __future__ import annotations

import atexit
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from ..log import get_logger

log = get_logger(__name__)

#: Enough to keep up with a person, few enough that a burst cannot spawn a
#: thread per message.
MAX_WORKERS = 2

#: How long `wait_for_idle` waits at process exit before giving up. Learning is
#: best-effort: losing the last extraction is better than hanging a quit.
SHUTDOWN_GRACE = 3.0

_pool: ThreadPoolExecutor | None = None
_lock = threading.Lock()
_pending: set[Future] = set()


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=MAX_WORKERS,
                                       thread_name_prefix="chitragupta-after")
        return _pool


def after_turn(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
    """Run `fn` once the caller has let go of the turn.

    Never raises, and never lets `fn` raise into nothing: a failure here is
    logged and dropped, because the user already has their answer and an
    exception in the brain's bookkeeping is not their problem.
    """
    def _guarded() -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            log.debug("after-turn work failed: %s", exc)
            return None

    future = _get_pool().submit(_guarded)
    with _lock:
        _pending.add(future)
    future.add_done_callback(lambda f: _pending.discard(f))
    return future


def wait_for_idle(timeout: float = 10.0) -> bool:
    """Block until the queued work is done. True if it finished in time.

    For tests, which need the brain to have caught up before they look at it,
    and for shutdown. Nothing in a request path should call this — waiting here
    is exactly what this module exists to avoid.
    """
    from concurrent.futures import wait

    with _lock:
        outstanding = set(_pending)
    if not outstanding:
        return True
    _done, not_done = wait(outstanding, timeout=timeout)
    return not not_done


@atexit.register
def _drain_on_exit() -> None:
    wait_for_idle(SHUTDOWN_GRACE)
