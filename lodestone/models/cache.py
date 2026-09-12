"""Short-lived caches for the expensive probes behind the model catalog.

Building the catalog shells out to vendor CLIs and pokes local daemons. Done
naively that costs seconds, and `/api/providers` and `/api/models/catalog` are
both requested every time the Models drawer opens — so the UI stalled.

These caches are deliberately short: long enough that one drawer open does the
work once, short enough that connecting an account is reflected immediately.
Every cache registers itself so `clear_provider_cache()` can flush the lot when
a credential changes.
"""
from __future__ import annotations

import functools
import threading
import time
from typing import Any, Callable

_registry: list[Callable[[], None]] = []


def ttl_cached(seconds: float) -> Callable:
    """Cache a zero-argument probe for `seconds`, thread-safely."""

    def decorate(fn: Callable) -> Callable:
        state: dict[str, Any] = {"at": 0.0, "value": None, "set": False}
        lock = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if args or kwargs:          # never cache a parameterised call
                return fn(*args, **kwargs)
            now = time.monotonic()
            with lock:
                if state["set"] and (now - state["at"]) < seconds:
                    return state["value"]
            value = fn()
            with lock:
                state.update(at=time.monotonic(), value=value, set=True)
            return value

        def clear() -> None:
            with lock:
                state.update(at=0.0, value=None, set=False)

        wrapper.cache_clear = clear     # type: ignore[attr-defined]
        _registry.append(clear)
        return wrapper

    return decorate


def clear_all() -> None:
    """Flush every probe cache — called when a credential changes."""
    for clear in _registry:
        clear()
    try:
        from ..config import forget_cached_secrets

        forget_cached_secrets()
    except Exception:
        pass
