"""The sync line must not claim a sweep worked when it did not.

Found while closing A12. `scheduler._sync_all` records every connector's error
in the summary, `/api/sync/status` returns it as `last_result`, and `brain.js`
rendered `last_run` alone — so after a pass in which every source failed, the
panel read *"auto every 30m · last 12:34"*.

That is the shape of failure the background loop is most prone to, and the one
`AUDIT.md` → A12 opens with: the brain quietly stops updating and the user finds
out days later, from somebody else. The data to say so was already on the wire.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
WEB = ROOT / "chitragupta/web"

CLEAN = {
    "enabled": True, "syncing": False, "interval_minutes": 30,
    "last_run": "2026-09-16T12:34:00+00:00",
    "last_result": {"gmail": {"added": 4, "errors": []},
                    "notion": {"added": 0, "errors": []}},
}


def _run(status):
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/sync_status.mjs"), str(WEB / "app.js")],
        input=json.dumps(status), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def _with_failures(**sources):
    return {**CLEAN, "last_result": {
        name: {"added": 0, "errors": [err]} for name, err in sources.items()}}


def test_a_clean_sweep_still_reads_as_clean():
    """The fix must not cry wolf — most sweeps succeed, and a warning on every
    one of them is a warning nobody reads."""
    out = _run(CLEAN)

    assert out["error"] is None, out["error"]
    assert "failed" not in out["text"]
    assert out["trouble"] is False
    assert "last" in out["text"], "the timestamp is still there"


def test_a_failed_source_is_named_next_to_the_timestamp():
    """The exact bug: a timestamp on its own is a claim that it worked."""
    out = _run(_with_failures(gmail="Google sign-in expired"))

    assert "gmail" in out["text"]
    assert "failed" in out["text"]
    assert out["trouble"] is True


def test_every_failed_source_is_named():
    """One name would send the user to fix one connector and leave the others
    broken, with the line then claiming everything was fine."""
    out = _run(_with_failures(gmail="expired", notion="401", linear="timeout"))

    for name in ("gmail", "notion", "linear"):
        assert name in out["text"], out["text"]


def test_the_sweeps_own_bookkeeping_is_not_mistaken_for_a_source():
    """`_cancelled`, `_deduped` and `_graph` are the scheduler talking to itself.

    Reading them as connectors would put "_graph failed" in front of a user,
    which is the internal-leak `CLAUDE.md` forbids.
    """
    out = _run({**CLEAN, "last_result": {
        "_cancelled": True, "_deduped": 3,
        "_graph": {"entities": 2, "facts": 5, "remaining": 0},
        "gmail": {"added": 1, "errors": []}}})

    assert out["failed"] == []
    assert "_" not in out["text"]
    assert out["trouble"] is False


def test_a_sync_in_progress_says_so_rather_than_reporting_the_last_one():
    """Mid-sweep, last time's failure is stale news and the live state is what
    matters."""
    out = _run({**_with_failures(gmail="expired"), "syncing": True})

    assert out["text"] == "syncing now…"
    assert out["trouble"] is False, "no stale warning while it is working"


def test_auto_sync_off_is_not_dressed_up_as_a_failure():
    out = _run({**_with_failures(gmail="expired"), "enabled": False})

    assert out["text"] == "auto-sync off"


def test_a_status_with_no_result_yet_does_not_throw():
    """First launch: nothing has swept, so there is no `last_result` at all."""
    out = _run({"enabled": True, "syncing": False, "interval_minutes": 30,
                "last_run": None})

    assert out["error"] is None
    assert "not yet" in out["text"]
    assert out["trouble"] is False
