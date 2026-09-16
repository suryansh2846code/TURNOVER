"""Where the browser lives, how it arrives, and how it is cleaned up.

`docs/BROWSER.md` chose a bundled Chromium driven over CDP, **downloaded on
first use rather than shipped**, and the download is what makes the decision
viable: the `.dmg` stays the size it is, and the browser arrives the way a vendor
CLI already does — one button, with progress, managed by us, never a terminal
instruction.

Three things this owns, and the third is a standing invariant rather than a
feature.

**The profile is ours.** `~/Library/Lodestone/browser/profile`. The user signs in
here, once, to the sites they want an agent to reach — so the blast radius of a
mistake is the set of sites somebody deliberately signed into *in this app*, not
everything they have ever logged into. It is not `secrets.json`: cookies are not
settings and `settings.set_secret` should not learn about them. `brain.export()`
walks the memory table and nothing else, so a cookie jar cannot leave in a
backup — worth stating because a future export that walked the home directory
would turn that into a credential leak dressed as a feature.

**The download is a job.** A refresh must not kill one mid-way, and the UI needs
progress, so it runs on a thread with observable state — the same shape as
`models/cli_manager.py`, which solved this first.

**Anything we spawn, we clean up — across runs.** A browser is a long-lived
process holding a profile lock, and this app has already been here: 158 orphaned
`claude auth login` processes on one machine, because the only handle lived in
module state and every launch forgot the last one. So a Chromium we start is
recorded to disk through `models/login_processes.py` — the generic reaper that
problem produced — and reaped on launch and on quit. Only recorded PIDs are ever
signalled, each re-checked against the command line recorded with it.

**What is not here yet: the driver.** `session.Driver` is the seam, and the CDP
implementation behind it is the next landing. Until it exists `open_session()`
refuses with a sentence a user can act on rather than pretending — a control that
cannot work is the failure `/CLAUDE.md` names first, and a browser layer that
half-drives a real browser is worse than one that says it is not ready.
"""
from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..log import get_logger, suppressed

log = get_logger(__name__)

#: Marker recorded with a spawned browser, so the reaper can recognise ours and
#: refuse to signal a PID that has since been reused by something else.
PROCESS_MARKER = "lodestone-browser"


class BrowserNotReadyError(RuntimeError):
    """The browser is not installed or cannot be driven yet.

    Carries text written for the user, not for a log: it reaches a tool result
    and a panel, and "FileNotFoundError" is not an answer to "why did that not
    work".
    """


def root() -> Path:
    """Everything this package stores, under the app's own home."""
    return get_settings().home / "browser"


def profile_dir() -> Path:
    """The persistent profile — the thing that makes a site "signed in"."""
    return root() / "profile"


def install_dir() -> Path:
    return root() / "chromium"


def executable() -> Path | None:
    """The managed browser binary, or None if it is not installed.

    Looked up on disk rather than remembered in a setting: a user who deleted the
    directory has uninstalled it, and a stored "yes it is installed" would make
    the app insist otherwise. Detection is not consent in `models/`; here,
    detection is the *only* truth about installation.
    """
    app = install_dir() / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
    if app.exists():
        return app
    plain = install_dir() / "chrome"
    return plain if plain.exists() else None


def is_installed() -> bool:
    return executable() is not None


def profile_sites() -> int:
    """How many origins the profile has state for, as a rough "is this set up".

    Deliberately a count and not a list: the list of sites a user has *signed
    into* is answered by `origins.list_grants()`, which is what they consented
    to. Reading their cookie jar to enumerate accounts would be the app snooping
    on itself.
    """
    if not profile_dir().exists():
        return 0
    return sum(1 for _ in profile_dir().glob("Default/Local Storage/**/*"))


# ── the download, as an observable job ──────────────────────────────────
@dataclass
class _Job:
    state: str = "idle"          # idle | running | done | error
    message: str = ""
    percent: int = 0
    error: str = ""
    started_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


_JOB = _Job()


def install_status() -> dict[str, Any]:
    """What the panel renders. Never raises — it is polled."""
    installed = is_installed()
    return {
        "installed": installed,
        "path": str(executable()) if installed else None,
        "profile": str(profile_dir()),
        "state": _JOB.state if _JOB.state != "idle" else (
            "done" if installed else "idle"),
        "message": _JOB.message,
        "percent": _JOB.percent if _JOB.state != "idle" else (
            100 if installed else 0),
        "error": _JOB.error,
        # Said up front, because 150 MB on a slow connection is a surprise worth
        # not having. The number is approximate and labelled as such.
        "approx_mb": 150,
        # The driver is the next landing; the UI must not offer to drive a
        # browser it cannot drive.
        "drivable": False,
    }


def start_install(fetch=None) -> dict[str, Any]:
    """Begin fetching the browser. Returns immediately; poll `install_status()`.

    `fetch` is the download implementation, injected so the job can be tested
    without reaching the network — the state machine is the part that has gone
    wrong before, not the bytes.
    """
    with _JOB.lock:
        if _JOB.state == "running":
            return install_status()
        if is_installed():
            return install_status()
        _JOB.state, _JOB.message, _JOB.percent = "running", "Starting…", 0
        _JOB.error, _JOB.started_at = "", time.time()

    worker = fetch or _download_chromium

    def run() -> None:
        def note(message: str, percent: int) -> None:
            _JOB.message, _JOB.percent = message, max(0, min(100, int(percent)))

        try:
            install_dir().mkdir(parents=True, exist_ok=True)
            worker(install_dir(), note)
            if not is_installed():
                raise BrowserNotReadyError(
                    "The download finished but no browser was found in it.")
            _JOB.state, _JOB.percent = "done", 100
            _JOB.message = "Ready."
        except Exception as exc:
            _JOB.state = "error"
            _JOB.error = str(exc)[:200]
            _JOB.message = f"Could not set up the browser: {_JOB.error}"
            log.warning("browser install failed: %s", exc)

    threading.Thread(target=run, daemon=True).start()
    return install_status()


def _download_chromium(target: Path, note) -> None:   # pragma: no cover - network
    """Fetch and unpack a Chromium build into `target`.

    Not implemented, and failing loudly rather than silently: this is the one
    part of the package that cannot be exercised offline, and a stub that
    pretended to succeed would make `install_status()` report a browser that is
    not there.
    """
    raise BrowserNotReadyError(
        "Setting up the browser is not available in this build yet.")


def uninstall() -> bool:
    """Remove the browser. Leaves the profile alone — that is the user's
    sign-ins, and deleting them because they removed a binary would be losing
    their state to our tidying."""
    if not install_dir().exists():
        return False
    shutil.rmtree(install_dir(), ignore_errors=True)
    _JOB.state, _JOB.percent, _JOB.message = "idle", 0, ""
    return True


def forget_everything() -> bool:
    """Delete the profile: every sign-in, every cookie, all of it.

    The heavy half of "sign-out is a real control". Separate from `uninstall()`
    on purpose — one is about disk space, the other is about access, and a user
    who means the second must not have to guess that the first does it.
    """
    if not profile_dir().exists():
        return False
    shutil.rmtree(profile_dir(), ignore_errors=True)
    log.info("browser profile deleted at the user's request")
    return True


# ── the live session ────────────────────────────────────────────────────
def open_session():
    """A `Session` over the managed browser.

    Raises `BrowserNotReadyError` with something a person can act on. Two
    different refusals, because "set it up" and "this build cannot drive it" call
    for different actions from the user and conflating them would send them to
    press a button that will not help.
    """
    if not is_installed():
        raise BrowserNotReadyError(
            "The browser has not been set up yet. Open Settings and choose "
            "“Set up browsing” — it is a one-time download of about 150 MB.")
    raise BrowserNotReadyError(
        "This build can store which sites you allow, but cannot drive the "
        "browser yet. Nothing is wrong with your setup.")


def reap() -> int:
    """Kill any browser we left behind, including from a previous run."""
    with suppressed("reaping a browser left over from a previous run"):
        from ..models.login_processes import reap_all

        return reap_all()
    return 0
