"""The Websites shelf — one card per site, with whichever account is signed in.

Connectors listed allowed sites as bare hostnames in a row of text. A person
scanning for "am I connected to LinkedIn" had to read addresses; a site they had
signed in to looked the same as one they had merely allowed.

The account is the part worth testing. A grant carries `{origin, host, may_read,
may_act, note}` and **no username**, so there is nothing to print for most sites
— and printing one we do not have would be worse than printing none.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
WEB = ROOT / "chitragupta/web"


def shelf(grants) -> dict:
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/website_shelf.mjs"), str(WEB / "browser.js")],
        input=json.dumps({"grants": grants}), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def sub(out: dict, label: str) -> str:
    return next(s for (n, s) in out["cards"] if n == label)


def test_the_shelf_lists_the_sites_people_ask_for():
    assert shelf([])["catalogue"] == ["LinkedIn", "WhatsApp", "X", "Discord", "Reddit"]


def test_every_card_carries_a_mark():
    """A logo is how this is scanned. A row of identical cards is a list again."""
    assert shelf([])["marks"] == 5


def test_an_unconnected_site_says_what_it_would_give_you():
    assert sub(shelf([]), "WhatsApp") == "Your chats, through WhatsApp Web."
    assert shelf([])["off"] == ["linkedin", "whatsapp", "x", "discord", "reddit"]


def test_a_connected_site_shows_the_account_when_there_is_one():
    out = shelf([{"host": "x.com", "note": "@suryansh"}])
    assert sub(out, "X") == "@suryansh"
    assert out["on"] == ["x.com"]


def test_a_connected_site_with_no_account_says_signed_in_and_nothing_more():
    """A grant has no username. Inventing one is worse than saying none."""
    assert sub(shelf([{"host": "linkedin.com", "note": ""}]), "LinkedIn") == "Signed in"


def test_the_flows_own_note_is_not_mistaken_for_an_account():
    """`signin.py` writes "signed in from Connectors" — that is where the
    connection came from, not who it is."""
    out = shelf([{"host": "linkedin.com", "note": "signed in from Connectors"}])
    assert sub(out, "LinkedIn") == "Signed in"


def test_a_site_added_by_hand_still_gets_a_card():
    """It would otherwise vanish from the shelf and appear only in the list
    below, which reads as the app having lost it."""
    out = shelf([{"host": "news.ycombinator.com", "note": ""}])
    assert sub(out, "news.ycombinator.com") == "Signed in"
    assert "news.ycombinator.com" in out["on"]


def test_a_subdomain_matches_its_site():
    """A grant on www. or m. is the same site, and two cards for one account
    would be two Disconnect buttons that each half-work."""
    out = shelf([{"host": "www.linkedin.com", "note": "Suryansh Singh"}])
    assert sub(out, "LinkedIn") == "Suryansh Singh"
    assert len(out["cards"]) == 5, "a duplicate card was made for the subdomain"
