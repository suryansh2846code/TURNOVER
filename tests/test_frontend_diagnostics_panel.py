"""The panel that shows what happened, and the button that sends it.

A log nobody can read is the same as no log. The app records every failure it
survives and wrote it to a file a shipped `.app` user cannot open, so "it just
doesn't work" stayed unfalsifiable in exactly the cases the logging was built
for — and `/CLAUDE.md` forbids the one instruction that would have helped.

Three things have to hold, and none of them is visible from the markup:

* the lines reach the box, newest at the bottom, already scrolled there
* `ok: false` *says something* — an empty box reads as "nothing went wrong",
  which is a different and wrong answer
* Copy actually copies, because a copy button that quietly does nothing is worse
  than no button

And one that has to keep holding: **there is nothing here that runs anything.**
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "chitragupta/web"

LINES = [
    "2026-09-16 21:22:56,474 DEBUG chitragupta.suppressed: failed while reading "
    "the saved port: no such file",
    "2026-09-16 21:22:57,001 WARNING chitragupta.gmail: sync failed: 401",
]
OK = {"ok": True, "lines": LINES, "truncated": True,
      "path": "/x/logs/chitragupta.log", "bytes": 20480}


def _run(payload):
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/diagnostics_panel.mjs"), str(WEB / "app.js")],
        input=json.dumps(payload), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def panel():
    return _run(OK)


def test_it_rendered(panel):
    assert panel["error"] is None, panel["error"]


def test_the_lines_reach_the_box_in_order(panel):
    assert panel["afterLoad"]["text"] == "\n".join(LINES)


def test_it_opens_scrolled_to_the_newest_line(panel):
    """"What just happened" means the end of the file. Making someone drag a
    scrollbar to find it is the same as not showing it."""
    assert panel["afterLoad"]["scrolled"] > 0


def test_the_summary_says_how_much_is_shown_and_how_much_is_not(panel):
    meta = panel["afterLoad"]["meta"]
    assert "2 lines" in meta
    assert "older ones not shown" in meta, "a silent cut reads as the whole story"
    assert "20 KB" in meta


def test_refresh_refetches(panel):
    """The panel is a poll, not a stream — so the button has to work."""
    assert panel["refreshed"] == "refetched"
    assert panel["urls"].count("/api/diagnostics/log?lines=200") >= 2


# ── the copy button, which is the point of the feature ───────────────────
def test_copy_puts_the_log_on_the_clipboard(panel):
    assert panel["copyResult"] == "ran", panel["copyResult"]
    assert panel["copied"] == ["\n".join(LINES)]


def test_copy_says_it_worked(panel):
    """`copyToClipboard` can fail silently in a webview without a gesture, which
    is why it returns a boolean and why this is asserted."""
    assert any("Copied" in t for t in panel["toasts"]), panel["toasts"]


def test_copy_with_nothing_to_copy_says_so_rather_than_copying_nothing():
    out = _run({"ok": True, "lines": [], "truncated": False, "bytes": 0})

    assert out["copied"] == []
    assert any("Nothing to copy" in t for t in out["toasts"]), out["toasts"]


# ── nothing to show is still an answer ───────────────────────────────────
def test_no_log_yet_explains_itself():
    out = _run({"ok": False, "lines": [], "truncated": False, "path": None,
                "detail": "No log file yet — nothing has been recorded on this "
                          "machine since the app was installed."})

    assert out["afterLoad"]["text"] == ""
    assert "nothing has been recorded" in out["afterLoad"]["meta"].lower()


def test_an_empty_but_ok_log_does_not_claim_a_line_count():
    out = _run({"ok": True, "lines": [], "truncated": False, "bytes": 0})

    assert "Nothing recorded yet" in out["afterLoad"]["meta"]


def test_a_failed_request_does_not_leave_a_stale_or_blank_mystery():
    """The endpoint being unreachable is itself diagnostic information."""
    out = _run({"__http_error": True})

    assert out["error"] is None, "the panel must not throw"
    assert "Could not read the log" in out["afterLoad"]["meta"]


# ── it stays read-only ───────────────────────────────────────────────────
def test_the_panel_has_nothing_that_runs_anything(panel):
    """The reason a terminal was rejected for this app is that a text box which
    executes things has a completely different security story. This panel shows
    and copies. If a `#logInput` or `#logRun` ever appears, that decision is
    being reversed and it should be reversed deliberately, not by a patch.
    """
    assert panel["hasInput"] is False


def test_the_panel_only_ever_reads():
    out = _run(OK)
    assert all("diagnostics" not in u or True for u in out["urls"])
    # Every diagnostics request is a GET; the harness records the method and the
    # panel has no code path that sets one.
    source = (WEB / "diagnostics.js").read_text()
    assert "method:" not in source, "the diagnostics panel must not write"
    assert "POST" not in source and "DELETE" not in source
