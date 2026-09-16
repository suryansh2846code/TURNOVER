"""Automations and reminders can be changed, not just made and unmade.

The Inbox page offers edit / create / delete for both. Before it, routines
could be created, toggled and deleted but never corrected — a typo in an
instruction meant deleting the automation and rebuilding it — and reminders
could only be listed and deleted, with no way to set one at all except by
asking an agent.

What is deliberately NOT editable matters as much as what is:

* `enabled` has its own toggle and `last_run` / `last_result` are the
  routine's record of what it actually did. Letting an edit form carry those
  would let a stale form erase a run history.
* A reminder that has already fired stays fired. Editing it would resurrect a
  notification the user has already seen and dealt with.
* The upcoming list carries queued ACTIONS as well as reminders — an email an
  agent is about to send. Those are not free text with a time on them, and a
  half-edited one is worse than one the user cancels and asks for again.
"""
import pytest

from chitragupta.reminders import get_reminders
from chitragupta.routines import get_routines


@pytest.fixture()
def routine():
    r = get_routines().create("Morning sweep", "inbox", "new_email",
                              "Summarise anything new", 60)
    yield r
    get_routines().delete(r["id"])


@pytest.fixture()
def reminder():
    r = get_reminders().add("call dev", "2030-01-01T09:00:00+00:00")
    yield r
    get_reminders().delete(r["id"])


# ── routines ──────────────────────────────────────────────────────────────
def test_an_automation_can_be_corrected_in_place(routine):
    out = get_routines().update(routine["id"], name="Evening sweep",
                                instruction="Summarise what changed")
    assert out["name"] == "Evening sweep"
    assert out["instruction"] == "Summarise what changed"
    assert out["id"] == routine["id"], "an edit must not make a new automation"


def test_only_the_named_fields_move(routine):
    """A form posting its whole state must not be able to erase the record."""
    get_routines().mark_run(routine["id"], "found 3 new emails")
    before = get_routines().get(routine["id"])
    get_routines().update(routine["id"], name="Renamed", enabled=0,
                          last_run=None, last_result="wiped")
    after = get_routines().get(routine["id"])
    assert after["name"] == "Renamed"
    assert after["enabled"] == before["enabled"]
    assert after["last_run"] == before["last_run"]
    assert after["last_result"] == before["last_result"]


def test_an_interval_of_zero_would_be_a_busy_loop(routine):
    assert get_routines().update(routine["id"], interval_min=0)["interval_min"] == 1


def test_blanking_a_name_is_not_an_edit(routine):
    assert get_routines().update(routine["id"], name="   ")["name"] == "Morning sweep"


def test_editing_nothing_leaves_it_alone(routine):
    assert get_routines().update(routine["id"])["name"] == "Morning sweep"


def test_editing_an_automation_that_is_gone_says_so():
    assert get_routines().update("no-such-id", name="x") is None


# ── reminders ─────────────────────────────────────────────────────────────
def test_a_reminder_can_be_reworded_and_moved(reminder):
    out = get_reminders().update(reminder["id"], message="call Dev about the launch",
                                 fire_at="2030-02-02T10:30:00+00:00")
    assert out["message"] == "call Dev about the launch"
    assert out["fire_at"].startswith("2030-02-02")


def test_a_reminder_that_already_fired_stays_fired(reminder):
    """Editing it would bring back a notification already dealt with."""
    get_reminders().mark_fired(reminder["id"])
    assert get_reminders().update(reminder["id"], message="too late") is None


def test_editing_a_reminder_that_is_gone_says_so():
    assert get_reminders().update("no-such-id", message="x") is None


# ── the routes ────────────────────────────────────────────────────────────
@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from chitragupta.api.app import app
    return TestClient(app)


def test_the_api_can_create_a_reminder(client):
    r = client.post("/api/reminders", json={"message": "stand up",
                                            "fire_at": "2030-03-03T09:00:00+00:00"})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert any(x["id"] == rid for x in client.get("/api/reminders").json()["reminders"])
    client.delete(f"/api/reminders/{rid}")


def test_a_reminder_with_nothing_to_say_is_refused(client):
    r = client.post("/api/reminders", json={"message": "   ",
                                            "fire_at": "2030-03-03T09:00:00+00:00"})
    assert r.status_code == 422


def test_the_api_edits_an_automation(client, routine):
    r = client.patch(f"/api/routines/{routine['id']}", json={"name": "Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Renamed"


def test_editing_something_that_is_gone_is_a_404_not_a_silent_success(client):
    assert client.patch("/api/routines/no-such-id", json={"name": "x"}).status_code == 404
    assert client.patch("/api/reminders/no-such-id", json={"message": "x"}).status_code == 404
