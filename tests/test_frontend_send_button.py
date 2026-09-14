"""The send button survives a turn.

It is 34px and round, and `setBusy` used to write `textContent` into it. That
is two bugs in one property: "Stop" does not fit a 34px circle, and writing
textContent replaces the element's children — so it deleted the arrow SVG that
`applyIcons` had put there. After the first message the send button was the
word "Send" for the rest of the session.

Both states assigned something, and both read as code that works, which is why
this runs the turn instead of reading the source.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"


@pytest.fixture(scope="module")
def states() -> dict:
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/send_button_state.mjs"), str(WEB / "app.js")],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return {s["state"]: s for s in json.loads(proc.stdout)}


@pytest.mark.parametrize("state", ["load", "busy", "idle"])
def test_the_button_always_holds_an_icon(states, state):
    s = states[state]
    assert s["hasIcon"], (
        f"in the {state!r} state the button contains {s['html'][:60]!r} — the "
        "icon was replaced, which is what writing textContent into it does")


def test_no_word_is_crammed_into_a_34px_circle(states):
    for state, s in states.items():
        assert not s["text"].strip(), (
            f"the {state!r} state put the text {s['text']!r} in the button")


def test_the_arrow_comes_back_after_a_turn(states):
    """The bug was permanent: once the first turn ended, the arrow was gone."""
    assert states["idle"]["html"] == states["load"]["html"], (
        "the button did not return to the state it started in")


def test_busy_and_idle_are_different_glyphs(states):
    assert states["busy"]["html"] != states["idle"]["html"]


def test_a_glyph_on_its_own_says_nothing_to_a_screen_reader(states):
    assert states["busy"]["aria"] == "Stop generating"
    assert states["idle"]["aria"] == "Send message"
    assert states["busy"]["title"] == "Stop"


def test_the_input_is_held_while_a_turn_runs(states):
    assert states["busy"]["inputDisabled"] is True
    assert states["idle"]["inputDisabled"] is False
