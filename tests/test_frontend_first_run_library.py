"""After onboarding, the Agent Library is the screen you land on.

Nothing is pre-added any more, so a workspace holding one lead agent and no way
to find the rest is a dead end. Naming the lead agent is the last step of
onboarding; the library is what follows it.

Executed rather than asserted from source: `createLead` catches its own
failures, so a silent abort partway through looks exactly like "the library did
not open" — which is what happened the first two times this ran.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"


def _run(which: str, seen: bool) -> dict:
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/first_run_library.mjs"), str(WEB / "app.js")],
        input=json.dumps({"path": which, "seen": seen}),
        capture_output=True, text=True, timeout=60)
    assert proc.stdout, proc.stderr[-2000:]
    return json.loads(proc.stdout)


@pytest.mark.parametrize("which", ["create", "skip"])
def test_the_library_opens_on_first_entry(which):
    out = _run(which, seen=False)
    assert out["error"] is None, out["error"]
    assert out["libraryOpen"] is True, (
        f"the library did not open after {which}; note was {out['note']!r}")


@pytest.mark.parametrize("which", ["create", "skip"])
def test_it_does_not_open_again_on_a_later_launch(which):
    out = _run(which, seen=True)
    assert out["error"] is None
    assert out["libraryOpen"] is False, "the library reopens on every launch"


def test_naming_a_lead_agent_still_works():
    """The library must not be reached by breaking the step before it."""
    out = _run("create", seen=False)
    assert out["leadStored"] == "atlas"
    assert "Couldn't create" not in out["note"], out["note"]


def test_the_library_does_not_wait_on_the_agents_welcome():
    """The welcome streams a model reply. A first screen that only appears when
    a model call succeeds is a first screen that sometimes does not appear."""
    source = (WEB / "workspace.js").read_text()
    body = source[source.index("async function createLead"):]
    body = body[:body.index("\n}")]
    assert body.index("libraryOnFirstRun()") < body.index("agentWelcome("), (
        "the library is opened after the streamed welcome, so a failed model "
        "call would leave the user on an empty rail")
