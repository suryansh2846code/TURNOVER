"""Tests for Brain v1.5 Foundation: Memory model, CRUD, types, temporal fields,
confidence, importance, provenance, reinforcement, access tracking, and status.
"""
import tempfile
from datetime import datetime, timezone
import pytest

from lodestone.brain import Brain
from lodestone.core.models import MemoryStatus, MemoryType
from lodestone.core.store import MemoryStore


@pytest.fixture
def store():
    db_file = tempfile.mktemp(suffix=".db")
    return MemoryStore(db_path=db_file)


@pytest.fixture
def brain(store):
    return Brain(store=store)


def test_memory_crud_and_v15_metadata(store):
    # 1. Create
    mem = store.add(
        "Suryansh builds local-first AI systems.",
        source="chat",
        kind="fact",
        memory_type=MemoryType.SEMANTIC.value,
        source_id="msg-101",
        event_time="2026-09-10T10:00:00Z",
        valid_from="2026-09-10",
        importance=0.9,
        confidence=0.95,
        extraction_method="user_statement",
        evidence="Direct user statement in chat",
        tags=["ai", "local-first"],
    )
    assert mem is not None
    assert mem.memory_type == MemoryType.SEMANTIC.value
    assert mem.source_id == "msg-101"
    assert mem.importance == 0.9
    assert mem.confidence == 0.95
    assert mem.status == MemoryStatus.ACTIVE.value
    assert mem.evidence == "Direct user statement in chat"
    assert "ai" in mem.tags

    # 2. Retrieve
    retrieved = store.get(mem.id)
    assert retrieved is not None
    assert retrieved.text == "Suryansh builds local-first AI systems."
    assert retrieved.confidence == 0.95
    assert retrieved.importance == 0.9

    # 3. Update
    updated = store.update(mem.id, importance=0.95, status=MemoryStatus.ACTIVE.value)
    assert updated is not None
    assert updated.importance == 0.95

    # 4. Soft delete (retract)
    ok = store.delete(mem.id, soft=True)
    assert ok is True
    retracted = store.get(mem.id)
    assert retracted.status == MemoryStatus.RETRACTED.value
    assert retracted.compute_activation() == 0.0

    # 5. Hard delete
    ok_hard = store.delete(mem.id, soft=False)
    assert ok_hard is True
    assert store.get(mem.id) is None


def test_memory_types_and_defaults(store):
    # Test mapping from legacy kind
    mem_pref = store.add("User prefers dark mode.", kind="preference")
    assert mem_pref.memory_type == MemoryType.PREFERENCE.value
    assert mem_pref.importance >= 0.8  # preferences receive high default importance

    mem_todo = store.add("Deploy production build by Friday.", kind="task")
    assert mem_todo.memory_type == MemoryType.COMMITMENT.value

    mem_email = store.add("Email from Aryan about YC batch.", kind="email")
    assert mem_email.memory_type == MemoryType.EPISODIC.value


def test_reinforcement_tracking(store):
    mem = store.add("The user lives in San Francisco.", confidence=0.75, reinforcement_count=0)
    assert mem.reinforcement_count == 0
    assert mem.last_reinforced_at is None

    # Reinforce
    ok = store.reinforce(mem.id)
    assert ok is True

    reloaded = store.get(mem.id)
    assert reloaded.reinforcement_count == 1
    assert reloaded.last_reinforced_at is not None
    assert reloaded.confidence > 0.75  # confidence boosted upon meaningful reinforcement


def test_access_tracking_and_activation(store):
    mem = store.add("Key architecture decision: SQLite as local storage.", importance=0.85, confidence=0.9)
    assert mem.access_count == 0
    assert mem.last_accessed_at is None

    # Compute baseline activation
    initial_activation = mem.compute_activation()
    assert 0.0 < initial_activation <= 1.0

    # Simulate recall access
    store.search("architecture decision", limit=5)

    reloaded = store.get(mem.id)
    assert reloaded.access_count >= 1
    assert reloaded.last_accessed_at is not None
    assert reloaded.compute_activation() >= initial_activation


def test_supersession_preserves_history(store):
    mem1 = store.add("User uses React for frontend.", valid_from="2025-01-01")
    mem2 = store.add("User switched to Vanilla JS and web components.", valid_from="2026-06-01")

    assert mem1.status == MemoryStatus.ACTIVE.value

    # Supersede mem1 with mem2
    store.supersede(mem1.id, mem2.id, valid_until="2026-06-01")

    old_mem = store.get(mem1.id)
    new_mem = store.get(mem2.id)

    # History is intact!
    assert old_mem.status == MemoryStatus.SUPERSEDED.value
    assert old_mem.valid_until == "2026-06-01"
    assert new_mem.status == MemoryStatus.ACTIVE.value
    assert new_mem.supersedes_id == mem1.id
