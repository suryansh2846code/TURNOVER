"""Logging, and a place to put failures we intend to survive.

The codebase is full of operations that genuinely may fail without the user
caring: a Keychain that is locked, a vendor CLI that is not installed, a
metadata probe for a provider nobody has connected. Written as
`try: ... except Exception: pass`, each of those is correct at runtime and
invisible afterwards — which is how a user's "it just doesn't work" becomes
unfalsifiable, because the one place that knew what went wrong threw it away.

`suppressed()` keeps the runtime behaviour exactly (the failure is still not
raised) and keeps the evidence. Debug output is off by default and costs
nothing; `CHITRAGUPTA_DEBUG=1` turns it on, and a rotating file in the Chitragupta
home means a bug report has something in it even when nobody was watching a
terminal.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_ROOT = "chitragupta"
_configured = False


def _log_dir() -> Path | None:
    """The Chitragupta home's log directory, or None if it cannot be written.

    Imported lazily: `config` reads settings and the environment, and logging
    must not drag that in at import time.
    """
    try:
        from .config import get_settings

        path = get_settings().home / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        return None


def configure(force: bool = False) -> None:
    """Attach handlers once, on first use.

    Idempotent, because every entry point (`serve`, `app`, the test suite, a
    script) may be the first to log and none of them owns the others.
    """
    global _configured
    if _configured and not force:
        return
    _configured = True

    root = logging.getLogger(_ROOT)
    root.setLevel(logging.DEBUG if os.environ.get("CHITRAGUPTA_DEBUG") else logging.INFO)
    root.propagate = False
    if root.handlers and not force:
        return

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    # Only real problems reach the terminal — the desktop app's stdout is not a
    # log viewer, and noise there trains people to ignore it.
    stream = logging.StreamHandler()
    stream.setLevel(logging.WARNING)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    directory = _log_dir()
    if directory is not None:
        try:
            from logging.handlers import RotatingFileHandler

            handler = RotatingFileHandler(
                directory / "chitragupta.log", maxBytes=2_000_000, backupCount=3,
                encoding="utf-8")
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(fmt)
            root.addHandler(handler)
        except Exception:
            # A log that cannot be written must never stop the app starting.
            pass


def get_logger(name: str) -> logging.Logger:
    """A logger under the `chitragupta` root. Pass `__name__`."""
    configure()
    if name == _ROOT or name.startswith(_ROOT + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT}.{name}")


@contextmanager
def suppressed(doing: str, *, logger: logging.Logger | None = None,
               level: int = logging.DEBUG) -> Iterator[None]:
    """Run a block whose failure is survivable, and record it rather than lose it.

    `doing` is a plain-language fragment naming the attempt, so the line reads
    as a sentence: `suppressed("reading the saved port")` →
    *"failed while reading the saved port: [Errno 2] ..."*.

    Deliberately catches `Exception` and not `BaseException`: a KeyboardInterrupt
    or a SystemExit is not a survivable failure and must keep travelling.
    """
    try:
        yield
    except Exception as exc:
        (logger or get_logger("suppressed")).log(
            level, "failed while %s: %s", doing, exc, exc_info=level <= logging.DEBUG)
