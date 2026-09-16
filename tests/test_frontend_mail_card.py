"""The card a person taps to change twelve emails at once.

Triage is where the batch matters: twenty approval cards is not a safer version
of one, it is the same act with the review worn out of it. So one card covers
the batch — and because it covers a batch, it has to say *which* emails, in
words, without a Gmail label id or a message id anywhere on it.

Executes the real `parseActions` + `actionCard`, because a card that renders
correctly in principle and throws in the browser is the bug this harness exists
for.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"

TRIAGE = {
    "type": "mail_triage",
    "params": {"items": [
        {"id": "18f9a0b2c", "do": "archive", "subject": "Flash sale ends tonight"},
        {"id": "18f9a0b31", "do": "archive", "subject": "Your weekly newsletter"},
        {"id": "18f9a0b44", "do": "mark_read", "subject": "Standup notes"},
        {"id": "18f9a0b55", "do": "label", "label": "Receipts",
         "subject": "Invoice 402 from Northwind"},
    ]},
}


def _run(action, result):
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/action_card_plain.mjs"), str(WEB / "app.js")],
        input=json.dumps({"action": action, "result": result}),
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def card():
    return _run(TRIAGE, {"ok": True, "detail": "Archive 2 emails, Mark read 1 email"})


def test_it_rendered(card):
    assert card["error"] is None, card["error"]


def test_the_title_counts_what_is_about_to_happen(card):
    assert "Archive 2 emails" in card["html"]
    assert "Mark read 1 email" in card["html"]


def test_it_names_the_emails_so_the_batch_can_be_checked(card):
    assert "Flash sale ends tonight" in card["html"]
    assert "Invoice 402 from Northwind" in card["html"]
    assert "Receipts" in card["html"]


def test_no_internals_reach_the_screen(card):
    html = card["html"]
    assert "18f9a0b2c" not in html, "a Gmail message id is on the card"
    assert "INBOX" not in html and "UNREAD" not in html, "a Gmail label id is"
    assert "mail_triage" not in html and "mark_read" not in html


def test_it_says_nothing_is_deleted(card):
    """Archiving sounds like deleting to most people, and it is not."""
    assert "Nothing is deleted" in card["html"]


def test_it_is_one_card_not_one_per_email():
    from_text = ('I will tidy these up.\n'
                 '<action type="mail_triage">'
                 '{"items":[{"id":"a","do":"archive","subject":"One"},'
                 '{"id":"b","do":"archive","subject":"Two"}]}'
                 "</action>")
    out = _parse(from_text)
    assert len(out["actions"]) == 1
    assert len(out["actions"][0]["params"]["items"]) == 2
    assert "<action" not in out["clean"], "the tag was left in the visible reply"


def test_a_malformed_batch_shows_no_card_rather_than_a_wrong_one():
    out = _parse('<action type="mail_triage">{items: oops}</action>')
    assert out["actions"] == []


def _parse(text):
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/action_card.mjs"), str(WEB / "app.js")],
        input=json.dumps({"text": text}),
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)
