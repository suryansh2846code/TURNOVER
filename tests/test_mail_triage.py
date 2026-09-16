"""Changing mail that already exists.

An agent could compose and send email for as long as this project has existed
and could not archive one message. The reason was never missing code — it was
the OAuth scope. `gmail.send` can only send; it cannot touch a message that
already exists, and archive / label / mark-read are all modifications of one.

Every test here pins one half of the fix: the scope that makes it possible, and
the batch-with-one-approval shape that makes it usable.

Contract: docs/development/mail-triage.md
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from lodestone import actions, mail_triage
from lodestone.agents import connector_grants
from lodestone.agents.approvals import describe
from lodestone.agents.permissions import NEVER_UNATTENDED
from lodestone.agents.tools import TOOL_DEFS
from lodestone.connectors import google_auth


class FakeGmail:
    """Records what it was asked to change, and says yes."""

    def __init__(self):
        self.batches: list[dict] = []
        self.labels_made: list[str] = []

    def modify_messages(self, ids, add=None, remove=None, interactive=False):
        self.batches.append({"ids": list(ids), "add": list(add or []),
                             "remove": list(remove or [])})
        return {"ok": True, "count": len(ids)}

    def ensure_label(self, name, interactive=False):
        self.labels_made.append(name)
        return {"ok": True, "id": f"Label_{len(self.labels_made)}", "created": True}


@pytest.fixture
def gmail(monkeypatch):
    fake = FakeGmail()
    monkeypatch.setattr(actions, "_writer", lambda source, capability: fake)
    monkeypatch.setattr(google_auth, "may_modify_mail", lambda: True)
    return fake


# ── why it could not, until now ──────────────────────────────────────────
def test_the_scope_that_makes_any_of_this_possible_is_asked_for():
    """`gmail.send` can only send. Archiving needs `gmail.modify`."""
    assert any("gmail.modify" in s for s in google_auth.SCOPES), (
        "without gmail.modify every triage call comes back 403 — this is the "
        "single reason an agent could not change the inbox")


def test_an_old_token_is_told_to_reconnect_rather_than_failing_at_google(monkeypatch):
    """A token issued before the scope change carries read and send only."""
    reached = {"n": 0}
    monkeypatch.setattr(google_auth, "may_modify_mail", lambda: False)
    monkeypatch.setattr(actions, "_writer",
                        lambda *a: SimpleNamespace(
                            modify_messages=lambda *a, **k: reached.__setitem__("n", 1)))

    out = actions.run_now("mail_triage", {"items": [{"id": "1", "do": "archive"}]})

    assert not out["ok"]
    assert out["reauth"] is True
    assert "Reconnect" in out["error"] or "reconnect" in out["error"]
    assert reached["n"] == 0, "it called Gmail knowing the call could not work"


def test_permanent_deletion_is_not_a_verb_we_offer():
    """`gmail.modify` permits trashing. Nothing here does."""
    assert "delete" not in mail_triage.OPERATIONS
    assert "trash" not in mail_triage.OPERATIONS
    assert "mail.google.com" not in " ".join(google_auth.SCOPES), (
        "that is the full-mailbox scope, which allows permanent deletion")


# ── one approval covers the batch ────────────────────────────────────────
def test_twenty_emails_are_one_batch_call_not_twenty(gmail):
    items = [{"id": f"m{i}", "do": "archive"} for i in range(20)]

    out = actions.run_now("mail_triage", {"items": items})

    assert out["ok"] and out["count"] == 20
    assert len(gmail.batches) == 1, "one approved act became many requests"
    assert gmail.batches[0]["remove"] == ["INBOX"]


def test_different_changes_are_grouped_one_call_each(gmail):
    out = actions.run_now("mail_triage", {"items": [
        {"id": "a", "do": "archive"}, {"id": "b", "do": "archive"},
        {"id": "c", "do": "mark_read"},
        {"id": "d", "do": "label", "label": "Receipts"}]})

    assert out["ok"]
    assert len(gmail.batches) == 3
    assert gmail.labels_made == ["Receipts"]


def test_archiving_keeps_the_message(gmail):
    actions.run_now("mail_triage", {"items": [{"id": "a", "do": "archive"}]})
    assert gmail.batches[0]["remove"] == ["INBOX"]
    assert gmail.batches[0]["add"] == [], "archiving must not add or delete anything"


# ── refused whole, never half ────────────────────────────────────────────
@pytest.mark.parametrize("bad, because", [
    ([{"id": "a", "do": "incinerate"}], "unknown verb"),
    ([{"do": "archive"}], "no id"),
    ([{"id": "a", "do": "label"}], "label with no label name"),
    ([], "nothing listed"),
    ("not a list", "not a list"),
])
def test_a_malformed_batch_changes_nothing(gmail, bad, because):
    out = actions.run_now("mail_triage", {"items": bad})
    assert not out["ok"], because
    assert gmail.batches == [], "it applied part of a batch it had refused"


def test_the_refusal_says_what_it_can_do_instead():
    _items, problem = mail_triage.parse_items([{"id": "a", "do": "incinerate"}])
    assert "archive" in problem and "mark_read" in problem


def test_a_tag_with_broken_json_is_dropped_never_guessed_at():
    assert actions.parse_actions('<action type="mail_triage">{oops</action>') == []
    parsed = actions.parse_actions(
        '<action type="mail_triage">{"items":[{"id":"a","do":"archive"}]}</action>')
    assert parsed[0]["params"]["items"] == [{"id": "a", "do": "archive"}]


def test_a_bare_list_is_accepted_too():
    parsed = actions.parse_actions(
        '<action type="mail_triage">[{"id":"a","do":"archive"}]</action>')
    assert parsed[0]["params"]["items"] == [{"id": "a", "do": "archive"}]


# ── the card a person reads ──────────────────────────────────────────────
def test_the_card_counts_first_and_names_the_emails():
    line = describe("mail_triage", {"items": [
        {"id": "1", "do": "archive", "subject": "Flash sale ends tonight"},
        {"id": "2", "do": "archive", "subject": "Weekly newsletter"},
        {"id": "3", "do": "label", "label": "Receipts", "subject": "Invoice 402"}]})

    assert "Archive 2 emails" in line
    assert "Flash sale ends tonight" in line
    assert "Receipts" in line


def test_the_card_shows_no_internals():
    line = describe("mail_triage", {"items": [
        {"id": "18f9a0b", "do": "archive", "subject": "Sale"},
        {"id": "18f9a0c", "do": "mark_read", "subject": "Notes"}]})

    assert "18f9a0b" not in line, "a message id reached the user"
    assert "INBOX" not in line and "UNREAD" not in line, "a Gmail label id did"
    assert "mail_triage" not in line and "mark_read" not in line


def test_a_long_batch_gives_a_count_rather_than_a_list_nobody_reads():
    items = [{"id": str(i), "do": "archive", "subject": f"Thing {i}"} for i in range(30)]
    line = mail_triage.summarise(items)
    assert "Archive 30 emails" in line
    assert "+24 more" in line


# ── it never runs on its own ─────────────────────────────────────────────
def test_changing_the_inbox_always_waits_for_one_tap():
    """A triage agent's input is text strangers wrote."""
    assert "mail_triage" in NEVER_UNATTENDED


# ── the agent can address a message at all ───────────────────────────────
def test_the_tools_that_return_ids_exist():
    """Triage is impossible without an id, and gmail_search returns prose."""
    assert "list_mail" in TOOL_DEFS
    assert "read_thread" in TOOL_DEFS
    assert "id" in TOOL_DEFS["list_mail"].description.lower()


def test_reaching_gmail_still_needs_permission():
    """The gate covered connector tools and not the user's own inbox."""
    assert connector_grants.connector_of("list_mail") == "gmail"
    assert connector_grants.connector_of("read_thread") == "gmail"
    assert connector_grants.connector_of("gmail_search") == "gmail"
    assert connector_grants.connector_of("search_brain") == ""


def test_every_gated_builtin_is_a_tool_that_exists():
    """A renamed tool falling out of the map is a tool that stops asking."""
    missing = [n for n in connector_grants.FIRST_PARTY_TOOLS if n not in TOOL_DEFS]
    assert not missing, f"gated but not defined: {missing}"
