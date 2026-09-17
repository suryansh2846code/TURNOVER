"""After onboarding, the Agent Library is the screen you land on.

Nothing is pre-added and there is no lead agent any more, so a new install has
NO agents at all — the library is not a nicety here, it is the only way to get
one. The rail says so whenever it is empty, and points there.

Executed rather than asserted from source: evaluating the app runs its real boot
sequence, which is the thing under test. An earlier version of this file drove
the "name your lead agent" card instead, and that card is gone.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "chitragupta/web"


def _boot(onboarded: bool, seen: bool) -> dict:
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/first_run_library.mjs"), str(WEB / "app.js")],
        input=json.dumps({"onboarded": onboarded, "seen": seen}),
        capture_output=True, text=True, timeout=60)
    assert proc.stdout, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_the_library_opens_on_first_entry():
    out = _boot(onboarded=True, seen=False)
    assert out["error"] is None, out["error"]
    assert out["libraryOpen"] is True, "there is no other way to get an agent"


def test_it_does_not_open_again_on_a_later_launch():
    out = _boot(onboarded=True, seen=True)
    assert out["error"] is None
    assert out["libraryOpen"] is False, "the library reopens on every launch"


def test_it_does_not_open_over_the_top_of_onboarding():
    """Somebody who has not onboarded is being redirected to it."""
    out = _boot(onboarded=False, seen=False)
    assert out["libraryOpen"] is False


def test_an_empty_rail_explains_itself():
    """Zero agents is a real first run, not an error — it has to lead
    somewhere rather than being blank."""
    out = _boot(onboarded=True, seen=True)
    assert out["agentsEmptyState"] is True


@pytest.mark.parametrize("gone", ["createLead", "maybeWelcome", "agentWelcome",
                                  "chitragupta_lead_agent"])
def test_the_lead_agent_flow_is_gone_from_the_frontend(gone):
    """It was a second definition of Chief of Staff. Leaving half of it behind
    is how a dead path gets called again by accident."""
    for name in ("workspace.js", "app.js", "chat.js"):
        assert gone not in (WEB / name).read_text(), f"{gone} survives in {name}"


def test_the_welcome_card_markup_is_gone():
    html = (WEB / "index.html").read_text()
    for gone in ("wName", "wCreate", "wSkip", "Meet your"):
        assert gone not in html, f"{gone} is still in index.html"
