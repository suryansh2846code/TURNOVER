"""The card a person taps to send a message on Telegram or Slack.

The app is named on it, and that is not decoration: the same handle is two
different people on two different apps, and "send a message to dana" does not
say which one is about to get it.

Executes the real `parseActions` + `actionCard`. A card that renders correctly
in principle and throws in the browser is what this harness exists for — and a
type with no branch of its own falls through to the calendar one, which would
present a Telegram message as "Create calendar event".
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"

MESSAGE = {
    "type": "message_send",
    "params": {"app": "telegram", "chat": "@dana",
               "text": "Running ten minutes late — see you at six."},
}


def _run(action, result):
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/action_card_plain.mjs"), str(WEB / "app.js")],
        input=json.dumps({"action": action, "result": result}),
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def _parse(text):
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/action_card.mjs"), str(WEB / "app.js")],
        input=json.dumps({"text": text}),
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def card():
    return _run(MESSAGE, {"ok": True, "detail": "Message sent on Telegram"})


def test_it_rendered(card):
    assert card["error"] is None, card["error"]


def test_the_app_is_named(card):
    assert "Telegram" in card["html"]
    assert "calendar" not in card["html"].lower(), (
        "it fell through to the calendar branch")


def test_the_recipient_and_the_message_are_both_shown(card):
    assert "@dana" in card["html"]
    assert "Running ten minutes late" in card["html"]


def test_no_internals_reach_the_screen(card):
    assert "message_send" not in card["html"]


def test_the_message_is_the_tag_body():
    out = _parse('One moment.\n<action type="message_send" app="slack" '
                 'chat="C024BE91L">On my way.</action>')
    assert len(out["actions"]) == 1
    assert out["actions"][0]["params"]["text"] == "On my way."
    assert out["actions"][0]["params"]["app"] == "slack"
    assert "<action" not in out["clean"], "the tag was left in the visible reply"
