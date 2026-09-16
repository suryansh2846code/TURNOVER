"""What just happened — the log, readable without a terminal.

`log.py` keeps every survivable failure rather than swallowing it, and that
evidence was written to a file no shipped user can open. "It just doesn't work"
therefore stayed unfalsifiable in exactly the cases the logging was built for: a
connector that needs Full Disk Access, a vendor CLI that would not install, a
sync that failed at 3am. `/CLAUDE.md` forbids sending anyone to a terminal, and
"open Console.app and find our file" is that instruction wearing a hat.

So this reads the tail of the current log and hands it back for a panel and a
Copy button. Three things it is deliberately not:

* **Not a stream.** A poll returning the tail is enough for "what just
  happened", and a websocket for one read-only panel is a second transport to
  maintain.
* **Not the whole file.** The tail is bounded here, not by the caller, because a
  2 MB response rendered into the DOM is a frozen window.
* **Not raw.** Every line goes through `redact()` — the same pass the ingest
  path uses — because an exception message can carry a bearer token and this
  panel exists to be **copied into a bug report**. That is the whole risk: the
  file was already on the user's disk, and what is new is how easily its
  contents travel. Verified against real lines: timestamps, ports and durations
  survive, `Bearer …`, `xai-…`, `ntn_…` and JWTs do not.
"""
from __future__ import annotations

import io
from pathlib import Path

from fastapi import APIRouter

from ...brain.canonical.redact import redact
from ...log import get_logger
from ...log import log_file as _log_file

log = get_logger(__name__)
router = APIRouter()

#: Most lines one request will return. Enough to cover a launch plus a sync
#: pass; small enough that the panel renders instantly.
MAX_LINES = 500

#: How far back from the end of the file to read. A generous multiple of
#: MAX_LINES × a long line, so the tail is never short because one traceback was
#: unusually wide. Reading from the end matters: the file rotates at 2 MB and
#: loading all of it to keep the last 200 lines is work nobody asked for.
_TAIL_BYTES = 512_000


def _tail(path: Path, lines: int) -> tuple[list[str], bool]:
    """The last `lines` lines, and whether anything was left above them."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        start = max(0, size - _TAIL_BYTES)
        handle.seek(start)
        raw = handle.read()
    # A mid-character seek is possible on a UTF-8 file, so decode forgivingly —
    # a diagnostics panel that 500s on a stray byte is worse than one showing a
    # replacement character.
    text = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace").read()
    if start:
        # The first line is almost certainly half of one.
        text = text.split("\n", 1)[-1]
    found = [ln for ln in text.splitlines() if ln.strip()]
    return found[-lines:], bool(start) or len(found) > lines


@router.get("/api/diagnostics/log")
def diagnostics_log(lines: int = 200):
    """Recent log lines, oldest first, secrets removed.

    `ok` is false only when there is no log to read, which is itself an answer —
    it means logging could not write to the app's home, and the panel says so
    rather than showing an empty box that reads as "nothing went wrong".
    """
    # Clamped rather than validated: a caller asking for 100,000 lines gets the
    # most we will send, not an error. There is no request here worth refusing.
    lines = max(1, min(int(lines or 200), MAX_LINES))
    path = _log_file()

    if path is None or not path.exists():
        return {"ok": False, "lines": [], "truncated": False, "path": None,
                "detail": "No log file yet — nothing has been recorded on this "
                          "machine since the app was installed."}

    try:
        found, truncated = _tail(path, lines)
    except OSError as exc:
        log.warning("could not read the log for diagnostics: %s", exc)
        return {"ok": False, "lines": [], "truncated": False, "path": str(path),
                "detail": "The log file could not be read."}

    return {"ok": True,
            "lines": [redact(ln) for ln in found],
            "truncated": truncated,
            "path": str(path),
            "bytes": path.stat().st_size}
