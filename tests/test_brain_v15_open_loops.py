"""Tests for Brain v1.5 Open Loops:
Lifecycle, priority, status transitions, recall integration, and agent tool access.
"""
import tempfile
import pytest

from lodestone.brain import Brain
from lodestone.core.models import OpenLoopPriority, OpenLoopStatus
from lodestone.core.store import MemoryStore


@pytest.fixture
def store():
    db_file = tempfile.mktemp(suffix=".db")
    return MemoryStore(db_path=db_file)


@pytest.fixture
def brain(store):
    return Brain(store=store)


def test_open_loop_lifecycle(brain):
    # 1. Create open loop
    loop = brain.create_open_loop(
        "Prepare the launch announcement for TURNOVER",
        priority=OpenLoopPriority.HIGH.value,
        due_at="2026-09-15",
        related_project="TURNOVER",
        related_entities=["Aryan", "Jai"],
    )
    assert loop["id"]
    assert loop["status"] == OpenLoopStatus.OPEN.value
    assert loop["priority"] == "high"
    assert loop["related_project"] == "TURNOVER"

    # 2. Retrieve open loops
    loops = brain.get_open_loops(status="open")
    assert len(loops) == 1
    assert loops[0]["id"] == loop["id"]

    # Filter by project
    turnover_loops = brain.get_open_loops(related_project="TURNOVER")
    assert len(turnover_loops) == 1
    other_loops = brain.get_open_loops(related_project="Nonexistent")
    assert len(other_loops) == 0

    # 3. Update open loop
    updated = brain.update_open_loop(loop["id"], priority="urgent")
    assert updated["priority"] == "urgent"

    # 4. Complete open loop
    done = brain.complete_open_loop(loop["id"])
    assert done["status"] == OpenLoopStatus.COMPLETED.value
    assert done["completed_at"] is not None

    # Verify no open loops remain
    remaining = brain.get_open_loops(status="open")
    assert len(remaining) == 0


def test_open_loops_injected_into_recall_context(brain):
    brain.create_open_loop(
        "Deploy the TURNOVER production build to staging",
        related_project="TURNOVER",
        priority="high",
    )
    brain.store.add("TURNOVER is the local-first AI workspace.")

    res = brain.recall("what is next for the TURNOVER project?")
    assert "ACTIVE OPEN LOOPS & COMMITMENTS:" in res["context"]
    assert "Deploy the TURNOVER production build to staging" in res["context"]
    assert len(res["open_loops"]) >= 1


def test_open_loops_agent_tools(brain, monkeypatch):
    from lodestone.agents.tools import _create_open_loop, _list_open_loops, _complete_open_loop
    monkeypatch.setattr("lodestone.agents.tools.get_brain", lambda: brain)

    # 1. Create via tool
    res = _create_open_loop("Follow up with client about API keys", related_project="ClientX")
    assert "Created open loop" in res

    # 2. List via tool
    listed = _list_open_loops(project="ClientX")
    assert "Follow up with client about API keys" in listed

    # 3. Complete via tool
    done_msg = _complete_open_loop("Follow up with client")
    assert "Completed open loop" in done_msg
    assert _list_open_loops(project="ClientX") == "No open loops."
