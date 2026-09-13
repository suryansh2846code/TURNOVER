"""Vendor-CLI logins must not outlive the app.

`claude auth login` waits for a browser callback that may never arrive. Nothing
reaped them — not a completed sign-in, not the timeout, not quitting — and the
handle lived in module state, so each launch forgot the last launch's. 158 were
found alive on one machine, each holding memory and the OAuth callback port.

Uses `sleep` rather than a real vendor CLI: the tests here have twice spawned
actual login flows on the developer's machine.
"""
import subprocess
import time

import pytest

from lodestone.models import login_processes


@pytest.fixture(autouse=True)
def _clean():
    login_processes.reap_all()
    yield
    login_processes.reap_all()


def _spawn():
    return subprocess.Popen(["sleep", "45"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _alive(proc) -> bool:
    return proc.poll() is None


def test_a_tracked_login_is_stopped_even_from_an_earlier_run():
    """The record is on disk precisely because the process that cleans up is
    not the one that made the mess."""
    proc = _spawn()
    try:
        login_processes.track(proc, "sleep")
        assert login_processes.reap_all() == 1
        time.sleep(0.6)
        assert not _alive(proc), "a stray login process survived the cleanup"
    finally:
        if _alive(proc):
            proc.kill()


def test_reaping_forgets_what_it_stopped():
    proc = _spawn()
    try:
        login_processes.track(proc, "sleep")
        login_processes.reap_all()
        assert login_processes.reap_all() == 0, "reaped the same PID twice"
    finally:
        if _alive(proc):
            proc.kill()


def test_a_recycled_pid_is_never_signalled():
    """PIDs get reused. Killing whatever inherited one would be far worse than
    the leak we are fixing, so the command line is re-checked first."""
    proc = _spawn()
    try:
        login_processes.track(proc, "this-is-not-what-is-running")
        assert login_processes.reap_all() == 0
        time.sleep(0.4)
        assert _alive(proc), "killed a PID whose command did not match"
    finally:
        proc.kill()


def test_released_processes_are_left_alone():
    proc = _spawn()
    try:
        login_processes.track(proc, "sleep")
        login_processes.release(proc.pid)
        assert login_processes.reap_all() == 0
        assert _alive(proc)
    finally:
        proc.kill()


def test_tracking_never_breaks_a_sign_in():
    """Bookkeeping failures must not fail the sign-in they are recording."""
    class NoPid:
        pass

    login_processes.track(NoPid(), "sleep")     # must not raise
    login_processes.release(None)
    assert login_processes.reap_all() == 0
