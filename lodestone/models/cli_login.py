"""One vendor-CLI sign-in, for every vendor that owns its own.

Cursor and xAI both ship a CLI whose `login` command opens the vendor's own
consent page, because the OAuth client belongs to that CLI — there is no private
client id to hold and no secret to bundle. So a "Sign in with X" button spawns
`X login` detached and polls a status command until it finishes.

That is one mechanism, and it was written twice. Normalising four names — the
status function, the binary finder, the brand, the vendor — and diffing
`cursor.py` against `grok_cli.py` left exactly two differences across ninety
lines: the docstring prose, and `["login"]` against `["login", "--oauth"]`.
Everything else, including the process bookkeeping that exists because 158
abandoned logins once accumulated on one machine, was identical.

Identical is not the problem. **Separately maintained** is: the two copies did
not have the same tests. `cursor.cancel_cli_login` was covered and
`grok_cli.cancel_cli_login` was not covered at all, so the same mistake made in
one file would have been caught and in the other would not. A fix applied to one
copy is a fix, and to one of two copies is a bug with a second home.

What genuinely differs per vendor stays with the vendor: how its binary is
found and verified, what its status command prints and how that is parsed, and
the TTL cache over it. What lives here is the state machine, and `augmented_path`
— the same six lines that were written a third time in `claude_code.py`, because
every one of these CLIs has to be found on a PATH that Finder stripped.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable

from . import login_processes


def augmented_path(extra_dirs: list[str]) -> str:
    """PATH extended with the bin directories a GUI-launched app cannot see.

    A process started from Finder inherits a stripped PATH — no Homebrew, no
    `~/.local/bin` — so a vendor CLI the user definitely installed is simply not
    found. Existing entries are never reordered and a directory that is not
    there is not added, so this can only widen the search.

    `extra_dirs` stays with the caller rather than being unified here: each
    module's list also drives the fallback scan in its `find_*` function, so a
    shared list would have Cursor's finder looking through `~/.grok/bin`.
    """
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for d in extra_dirs:
        if d and d not in parts and os.path.isdir(d):
            parts.append(d)
    return os.pathsep.join(parts)


def _still_running(proc: object) -> bool:
    """Is this process still waiting on the browser?

    Written against `poll` rather than an isinstance check because the tests
    substitute a stand-in, and because a `None` handle has to answer this too.
    """
    poll = getattr(proc, "poll", None)
    return callable(poll) and poll() is None


class CliLoginSession:
    """The in-flight `login` for one vendor CLI.

    Holds what used to be a pair of module globals. That is the other half of
    the point: two modules each carrying mutable process state is why the test
    suite needs an autouse fixture to reset them between tests, and why a stale
    handle from one test could be read by the next.
    """

    def __init__(self, *, brand: str, find_cli: Callable[[], str | None],
                 auth_status: Callable[..., dict], invalidate_cache: Callable[[], None],
                 login_args: list[str], install_hint: str,
                 env_path: Callable[[], str]) -> None:
        self.brand = brand
        self._find_cli = find_cli
        self._auth_status = auth_status
        self._invalidate_cache = invalidate_cache
        self._login_args = login_args
        self._install_hint = install_hint
        self._env_path = env_path
        #: The spawned `login`, and who was signed in when it started.
        self.proc: subprocess.Popen | None = None
        self.baseline: dict | None = None

    def reset(self) -> None:
        """Forget any in-flight login (used on disconnect, and by tests)."""
        self.proc, self.baseline = None, None

    def start(self) -> tuple[bool, str]:
        """Run the CLI's own browser sign-in, detached.

        Progress is observed by polling the vendor's status command, never by
        waiting on the process — the user may take minutes, and an account
        switch with a password and 2FA takes longer than any poll window.
        """
        cli = self._find_cli()
        if not cli:
            return False, self._install_hint
        # Remember who was signed in before, so an existing session is not
        # mistaken for the sign-in about to start.
        self.baseline = self._auth_status(fresh=True)
        self._invalidate_cache()          # the answer is about to change
        try:
            self.proc = subprocess.Popen(
                [cli, *self._login_args],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env={**os.environ, "PATH": self._env_path()},
                start_new_session=True)
            login_processes.track(self.proc, "login")
        except Exception as exc:
            return False, f"Could not start {self.brand} sign-in: {exc}"
        return True, f"Opened {self.brand} sign-in in your browser."

    def progress(self) -> dict:
        """How an in-flight `login` is going.

        Completion is the CLI's process exiting, not the account merely looking
        authenticated: re-signing in while already signed in would otherwise
        report success on the first poll, before the user had touched the
        browser.
        """
        baseline = self.baseline or {}
        # Only bypass the TTL cache once the process is gone — that is the
        # moment the cached answer is known to be stale.
        current = self._auth_status(
            fresh=self.proc is not None and not _still_running(self.proc))
        running = _still_running(self.proc)
        changed_account = (
            bool(current.get("email")) and current.get("email") != baseline.get("email"))
        newly_authed = bool(current.get("authenticated")) and not baseline.get("authenticated")
        return {
            "in_flight": self.proc is not None,
            "running": running,
            "authenticated": bool(current.get("authenticated")),
            "email": current.get("email"),
            # Either the process finished, or the account visibly changed.
            "done": bool(current.get("authenticated")) and (
                not running or changed_account or newly_authed),
        }

    def cancel(self) -> bool:
        """Stop an in-progress `login`. The browser tab stays open; the user
        simply never finishes, and nothing is recorded."""
        proc, self.proc = self.proc, None
        self.baseline = None
        self._invalidate_cache()
        if proc is None or not callable(getattr(proc, "poll", None)) or proc.poll() is not None:
            return False
        try:
            proc.terminate()
            return True
        except Exception:
            return False
        finally:
            # Release whether or not the signal landed. A row left pointing at a
            # dead PID is a row pointing at whatever the OS reuses it for.
            login_processes.release(getattr(proc, "pid", None))
