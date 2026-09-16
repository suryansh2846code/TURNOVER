"""An agent can see what it set running.

It could create a routine — "every morning, summarise my inbox" — and then had
no idea any existed: it could not list them, pause one, or see that an action it
proposed was sitting in a queue waiting for a tap. "What automations do I have
running?" was unanswerable by the thing that set them up. A routine nobody can
see is a routine nobody can trust, and that matters most for the ones that act
on their own.
"""
from __future__ import annotations

import pytest

from chitragupta.agents.permissions import NEVER_UNATTENDED
from chitragupta.agents.presets import PRESETS
from chitragupta.agents.tools import TOOL_DEFS, TOOL_IMPLS, build_tools, run_tool
from chitragupta.routines import get_routines


@pytest.fixture
def a_routine():
    store = get_routines()
    made = store.create("Morning inbox digest", "inbox", "schedule",
                        "Summarise anything new", interval_min=60)
    rid = made["id"] if isinstance(made, dict) else made
    yield rid
    store.delete(rid)


def test_an_agent_can_see_what_it_set_running(a_routine):
    out = run_tool("list_routines", {})
    assert out.ok
    assert "Morning inbox digest" in out
    assert "running" in out


def test_with_nothing_set_up_it_says_so():
    for r in get_routines().list():
        get_routines().delete(r["id"])
    out = run_tool("list_routines", {})
    assert out.ok
    assert "No automations" in out


def test_an_agent_can_pause_and_resume_one(a_routine):
    paused = run_tool("pause_routine", {"routine": "Morning inbox"})
    assert paused.ok, paused
    assert "paused" in paused
    assert "paused" in run_tool("list_routines", {})

    back = run_tool("pause_routine", {"routine": "Morning inbox", "resume": True})
    assert back.ok
    assert "running again" in back


def test_pausing_something_that_is_not_there_says_what_is(a_routine):
    out = run_tool("pause_routine", {"routine": "nonexistent thing"})
    assert not out.ok
    assert "Morning inbox digest" in out, "the failure did not say what does exist"


def test_pausing_needs_a_name():
    assert not run_tool("pause_routine", {"routine": ""}).ok


def test_queued_actions_are_visible_and_not_claimed_as_done():
    out = run_tool("list_pending_approvals", {})
    assert out.ok
    if "Nothing is waiting" not in out:
        assert "Do not claim" in out, (
            "an agent could read this list and report the actions as sent")


def test_scheduled_actions_are_visible():
    assert run_tool("list_scheduled", {}).ok


def test_creating_a_routine_is_still_gated_but_seeing_them_is_not():
    """Pausing takes authority away; creating grants it. Only one needs a tap."""
    assert "create_routine" in NEVER_UNATTENDED
    assert "pause_routine" not in NEVER_UNATTENDED
    assert "list_routines" not in NEVER_UNATTENDED


def test_deleting_is_deliberately_not_offered():
    """Pausing is reversible. Deleting is not, so an agent does not get it."""
    assert "delete_routine" not in TOOL_DEFS
    assert "delete_routine" not in TOOL_IMPLS


def test_the_shipped_agents_get_them():
    for agent in PRESETS.values():
        names = {t.name for t in build_tools(agent.tools, self_id=agent.id)}
        assert "list_routines" in names, f"{agent.id} cannot see its own automations"
        assert "list_pending_approvals" in names
