"""A blocked connector must offer the way out, and only where it exists.

Messages, Apple Mail and Apple Calendar read files macOS protects. When it says
no, the backend now sends `fix: "full_disk_access"` alongside the reason, and
the row is supposed to turn that into a button that opens the right System
Settings pane.

Two runtime-only failures this pins, neither visible to `node --check`:

* The status line preferred `meta.desc` over `c.reason`, so the explanation the
  backend worked to write never reached the screen at all — the row said
  "Reads your local iMessages", which is true and useless when macOS is the
  thing in the way.
* The button needs the pywebview bridge, which exists in the desktop app and
  not in a browser tab. Rendering it in a tab would ship a control that cannot
  work — the thing CLAUDE.md names as reading like "the app is broken".
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "chitragupta" / "web" / "app.js"
HARNESS = ROOT / "tests" / "js" / "connector_row_fix.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is needed to execute the frontend")

BLOCKED = {
    "name": "imessage", "label": "Messages", "ready": False,
    "reason": ("macOS is blocking access to your Messages. Open System Settings "
               "→ Privacy & Security → Full Disk Access, turn on Chitragupta, "
               "then try again."),
    "fix": "full_disk_access", "state": None,
}


def run(scenario: dict) -> dict:
    out = subprocess.run(
        ["node", str(HARNESS), str(APP_JS)],
        input=json.dumps(scenario), capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, f"harness failed:\n{out.stderr}"
    result = json.loads(out.stdout)
    assert result["ok"], f"render threw: {result['error']}"
    return result


def test_the_desktop_app_offers_the_button():
    r = run({"bridge": True, "connector": BLOCKED})
    assert r["hasFixButton"], (
        "a blocked connector rendered no way to fix it — the user is told to "
        "go to System Settings and left to find it themselves")


def test_a_browser_tab_does_not_offer_a_button_that_cannot_work():
    r = run({"bridge": False, "connector": BLOCKED})
    assert not r["hasFixButton"], (
        "the fix button needs the native bridge; in a browser tab it does "
        "nothing, and a control that cannot work reads as a broken app")
    assert "Full Disk Access" in r["status"], (
        "with no button, the sentence is the only way out and must still be "
        "the thing the row says")


def test_the_reason_reaches_the_screen_rather_than_the_catalogue_blurb():
    """The original bug: `meta.desc || c.reason` meant the blurb always won."""
    r = run({"bridge": True, "connector": BLOCKED})
    assert "macOS is blocking" in r["status"], (
        f"the row explained nothing; it said {r['status']!r}")
    assert "Chitragupta" in r["status"], "it does not say which app to switch on"


def test_a_blocked_row_does_not_also_offer_connect():
    """"Connect" opens setup instructions for a connector that is already set
    up correctly — the problem is permission, not configuration. Two buttons
    disagreeing about what is wrong is worse than one."""
    r = run({"bridge": True, "connector": BLOCKED})
    assert not r["hasConnectButton"]


def test_an_ordinary_unconnected_row_is_untouched():
    """Most refusals have no one-click fix, and must still look normal."""
    plain = {"name": "notion", "label": "Notion", "ready": False,
             "reason": "no NOTION_TOKEN", "fix": None, "state": None}
    r = run({"bridge": True, "connector": plain})
    assert not r["hasFixButton"]
    assert r["hasConnectButton"], "the normal Connect path regressed"
