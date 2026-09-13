"""Build an expensive singleton exactly once, even under concurrent callers.

`@lru_cache` looks like it does this and does not. It stores the result *after*
the call returns, so while a slow constructor is still running every other
caller misses and starts its own. The cache is a memo, never a lock.

That is invisible until the constructor is slow and the callers are concurrent,
which is exactly this app: loading the local embedding model takes ~10s, and the
scheduler thread plus FastAPI's worker threads all reach for it during startup.
Measured on this machine, `get_embedder()` — already `@lru_cache`d — ran its
body **five** times on a single launch:

    misses=1,2,3,4,5   hits=0   currsize=0

Five copies of the same model: **+44 MB of resident memory** and roughly forty
seconds of redundant CPU, every launch, on the threads the UI also needs.

`once()` closes the window with double-checked locking. The first caller builds
while the others wait on the lock; they then see the finished value and return
it. The second check inside the lock is what makes it correct — without it, a
caller that was already waiting when the first one finished would build a
second time.

Deliberately not `functools.cache` plus a global lock at the call site: that is
the same three lines written once per singleton, and the one that forgets is the
expensive one.
"""
from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

_MISSING = object()


def once(fn: Callable[[], T]) -> Callable[[], T]:
    """Memoise a zero-argument factory, serialising concurrent first calls.

    The wrapper carries `cache_clear()` so it is a drop-in for `lru_cache` —
    the test suite relies on clearing these between cases, and a singleton that
    cannot be reset would pin one test's temporary home for the whole run.
    """
    lock = threading.Lock()
    cell: list[Any] = [_MISSING]

    @functools.wraps(fn)
    def wrapper() -> T:
        # Fast path: no lock once the value exists, which is every call after
        # the first and is the only one that happens often.
        value = cell[0]
        if value is not _MISSING:
            return value                      # type: ignore[return-value]
        with lock:
            # Checked again inside the lock: a caller that was waiting while
            # the first one built must return *that* value, not build another.
            if cell[0] is _MISSING:
                cell[0] = fn()
            return cell[0]                    # type: ignore[return-value]

    def cache_clear() -> None:
        with lock:
            cell[0] = _MISSING

    def cache_info() -> dict[str, bool]:
        return {"cached": cell[0] is not _MISSING}

    wrapper.cache_clear = cache_clear         # type: ignore[attr-defined]
    wrapper.cache_info = cache_info           # type: ignore[attr-defined]
    return wrapper
