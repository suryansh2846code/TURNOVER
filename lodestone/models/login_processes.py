"""Track the vendor-CLI login processes we spawn, so we can clean up after them.

A `claude auth login` sits and waits for a browser callback that may never
arrive. Nothing reaped them: not a completed sign-in, not the timeout, not
quitting the app — and the only handle lived in module state, so every launch
forgot the previous launch's. They accumulate across runs (158 were found alive
on one machine), each holding memory and the vendor's OAuth callback port, until
sign-in stops working and the app has to be force-quit.

The record is on disk because the problem spans runs: the process that has to do
the cleaning is not the one that made the mess.

Only PIDs written here are ever signalled, and each is re-checked against the
command we recorded before it is touched — a PID is reused by the OS, and
killing whatever inherited it would be far worse than the leak.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_FILE = "login-processes.json"


def _path() -> Path:
    from ..config import get_settings

    return get_settings().home / _FILE


def _load() -> list[dict]:
    try:
        data = json.loads(_path().read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(rows: list[dict]) -> None:
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows[-50:]))
    except Exception:
        logger.debug("could not record login processes", exc_info=True)


def _command_of(pid: int) -> str:
    """What this PID is running now, or "" if it is gone."""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    except Exception:
        return ""


def track(proc, marker: str) -> None:
    """Record a login process. `marker` is matched against the live command line
    before we ever signal the PID.

    Bookkeeping must never be the reason a sign-in fails, so every failure here
    is swallowed: the cost is a stray process, which is what we already had.
    """
    try:
        pid = int(getattr(proc, "pid", 0) or 0)
        if pid <= 0:
            return
        rows = [r for r in _load() if r.get("pid") != pid]
        rows.append({"pid": pid, "marker": marker, "at": time.time()})
        _save(rows)
    except Exception:
        logger.debug("could not track login process", exc_info=True)


def release(pid: int | None) -> None:
    """Stop tracking a process we have already dealt with."""
    try:
        pid = int(pid or 0)
        if pid > 0:
            _save([r for r in _load() if r.get("pid") != pid])
    except Exception:
        logger.debug("could not release login process", exc_info=True)


def _terminate(pid: int, marker: str) -> bool:
    cmd = _command_of(pid)
    if not cmd:
        return False                      # already gone
    if marker and marker not in cmd:
        return False                      # PID reused by something else
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        logger.debug("could not stop login process %s", pid, exc_info=True)
        return False


def reap_all() -> int:
    """Stop every login process we started, including previous runs'. Returns how
    many were still alive."""
    rows = _load()
    stopped = sum(1 for r in rows if _terminate(int(r.get("pid", 0)), r.get("marker", "")))
    _save([])
    return stopped


def alive() -> list[dict]:
    """Tracked processes still running — for diagnostics, not flow control."""
    out = []
    for r in _load():
        cmd = _command_of(int(r.get("pid", 0)))
        if cmd and r.get("marker", "") in cmd:
            out.append({"pid": r["pid"], "command": cmd[:80]})
    return out
