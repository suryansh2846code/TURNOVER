"""`@` attaches a connector to one message, and you can see it before you send.

An agent must ask before it reaches a connector. `@` is how the user answers
that in advance, for a single turn — no card, no standing grant. The chips are
rendered before sending deliberately: a permission you cannot see at the moment
you grant it is not a permission you granted.

Executed, not grepped. The first version of this picker was silently dead:
`workspace.js` already had an `openPicker` (for folders) and loads later, so it
overwrote this one in the shared script scope. Source-order checks pass on that.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"
LABELS = {"gmail": "Gmail", "gcal": "Google Calendar", "notion": "Notion"}


def _drive(typed: str, choose: bool = False, labels=None) -> dict:
    # `labels or LABELS` would send the full set for `{}`, which is exactly the
    # case worth testing — an empty dict is falsy and "nothing connected" is a
    # real state, not an omission.
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/connector_picker.mjs"), str(WEB / "app.js")],
        input=json.dumps({"typed": typed, "choose": choose,
                          "labels": LABELS if labels is None else labels}),
        capture_output=True, text=True, timeout=60)
    assert proc.stdout, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_at_offers_everything_connected():
    out = _drive("@")
    assert out["error"] is None, out["error"]
    assert out["pickerOpen"] is True
    assert set(out["offered"]) == set(LABELS)


@pytest.mark.parametrize("typed,expected", [
    ("@gm", ["gmail"]), ("@no", ["notion"]), ("@goog", ["gcal"]),
])
def test_typing_narrows_it(typed, expected):
    """Matches on the id and on the name a person would type."""
    assert _drive(typed)["offered"] == expected


@pytest.mark.parametrize("typed", ["hi there", "a@b.com", "email me at x@y.co"])
def test_it_does_not_fire_on_an_email_address(typed):
    """`@` only opens it when it starts a word."""
    assert _drive(typed)["pickerOpen"] is False


def test_choosing_attaches_it_and_removes_the_half_typed_mention():
    out = _drive("look at @gm", choose=True)
    assert out["attached"] == ["gmail"]
    assert "@gm" not in out["inputAfter"], (
        "the agent would be sent a word it has to ignore")
    assert out["inputAfter"].strip() == "look at"


def test_the_chip_is_visible_before_sending():
    """A permission you cannot see when you grant it is not one you granted."""
    out = _drive("@gm", choose=True)
    assert out["chipsShown"] is True
    assert "Gmail" in out["chipsHtml"], "it shows the id instead of the name"
    assert "data-drop-connector" in out["chipsHtml"], "there is no way to undo it"


def test_nothing_connected_means_no_picker():
    assert _drive("@", labels={})["pickerOpen"] is False


def test_the_picker_functions_are_not_named_so_generically_they_collide():
    """`openPicker` was already taken by the folder picker in workspace.js,
    which loads later and overwrote this one."""
    chat = (WEB / "chat.js").read_text()
    for generic in ("function openPicker(", "function closePicker(",
                    "function updatePicker("):
        assert generic not in chat, f"{generic} will be shadowed"
