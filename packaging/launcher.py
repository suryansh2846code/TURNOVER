"""The .app's entry point.

A bundled app is not started from a shell, so it inherits no PATH, no
environment and no working directory worth having. `chitragupta app` assumes the
opposite in a few places — most visibly when it looks for vendor CLIs — so the
launcher restores the pieces that matter before handing over.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _restore_path() -> None:
    """Put the usual tool locations back on PATH.

    A GUI process on macOS gets PATH from launchd (`/usr/bin:/bin:/usr/sbin:/sbin`),
    not from the user's shell profile — so Homebrew, and anything the user
    installed themselves, is simply invisible. `find_*_cli()` prefers our own
    pinned copies in ~/Library/Chitragupta/bin, but it also falls back to PATH,
    and a CLI the user already had should still be found.
    """
    home = Path.home()
    extra = [
        str(home / "Library" / "Chitragupta" / "bin"),   # the CLIs we manage
        "/opt/homebrew/bin", "/usr/local/bin",
        str(home / ".local" / "bin"), str(home / ".bun" / "bin"),
        str(home / ".npm-global" / "bin"),
    ]
    current = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join(
        [p for p in extra if p not in current] + current)


def main() -> None:
    _restore_path()
    # A bundled app's cwd is "/", which makes any relative path a surprise.
    os.chdir(str(Path.home()))

    from chitragupta.desktop import run_app
    run_app(dev=False)


if __name__ == "__main__":
    sys.exit(main())
