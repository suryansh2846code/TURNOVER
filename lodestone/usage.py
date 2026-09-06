"""Persistent LLM token-usage accounting.

Every model call that goes through get_provider() records its input/output tokens
here (with a length-based estimate for providers that don't report usage). Stored
in the brain's meta table so it survives restarts and the desktop app's port
changes — that's why session tokens no longer vanish on refresh.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

_lock = threading.Lock()


def _store():
    from .core.store import get_store
    return get_store()


def _load(st) -> dict[str, Any]:
    raw = st.get_meta("usage")
    try:
        d = json.loads(raw) if raw else None
    except Exception:
        d = None
    if not isinstance(d, dict):
        d = {}
    d.setdefault("total", {"in": 0, "out": 0, "calls": 0})
    d.setdefault("by_provider", {})
    d.setdefault("updated", None)
    return d


def record(provider: str, model: str | None, tin: int, tout: int, calls: int = 1) -> None:
    if not provider or (tin <= 0 and tout <= 0):
        return
    with _lock:
        st = _store()
        d = _load(st)
        e = d["by_provider"].setdefault(provider, {"in": 0, "out": 0, "calls": 0, "model": model})
        e["in"] += int(tin); e["out"] += int(tout); e["calls"] += calls
        if model:
            e["model"] = model
        d["total"]["in"] += int(tin); d["total"]["out"] += int(tout); d["total"]["calls"] += calls
        d["updated"] = datetime.now(timezone.utc).isoformat()
        st.set_meta("usage", json.dumps(d))


def get() -> dict[str, Any]:
    return _load(_store())


def reset() -> None:
    with _lock:
        _store().set_meta("usage", "")
