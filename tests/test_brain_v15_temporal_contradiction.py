"""Tests for Brain v1.5 Temporal Reasoning and Contradiction Management."""
import tempfile
import pytest

from lodestone.brain import Brain
from lodestone.core.models import MemoryStatus
from lodestone.core.store import MemoryStore


@pytest.fixture
def store():
    db_file = tempfile.mktemp(suffix=".db")
    return MemoryStore(db_path=db_file)


@pytest.fixture
def brain(store):
    return Brain(store=store)


def test_temporal_validity_window(store):
    mem = store.add(
        "User worked at Acme Corp.",
        valid_from="2023-01-01",
        valid_until="2025-12-31",
        status=MemoryStatus.ACTIVE.value,
    )
    # Valid in 2024
    assert mem.is_valid_at("2024-06-15") is True
    # Not valid before 2023
    assert mem.is_valid_at("2022-05-01") is False
    # Not valid in 2026
    assert mem.is_valid_at("2026-01-01") is False


def test_detect_contradicting_preferences(brain):
    # Fact 1: prefers dark mode
    m1 = brain.store.add(
        "I prefer dark mode in all editors.",
        source="chat",
        kind="preference",
        confidence=0.9,
    )
    # Fact 2: prefers light mode
    m2 = brain.store.add(
        "I prefer light mode during daytime.",
        source="chat",
        kind="preference",
        confidence=0.9,
    )

    conflicts = brain.detect_contradictions()
    assert len(conflicts) >= 1
    c = conflicts[0]
    assert "dark mode vs light mode" in c["topic"]
    assert c["older_id"] == m1.id
    assert c["newer_id"] == m2.id

    # Resolve conflict via superseding
    res = brain.resolve_contradiction(c, auto_supersede=True)
    assert res["action"] == "superseded"

    # Verify history is preserved
    old_m = brain.store.get(m1.id)
    new_m = brain.store.get(m2.id)
    assert old_m.status == MemoryStatus.SUPERSEDED.value
    assert new_m.status == MemoryStatus.ACTIVE.value


def test_detect_direct_negation_contradiction(brain):
    m1 = brain.store.add("I use React for frontend development.", confidence=0.85)
    m2 = brain.store.add("I am moving away from React completely.", confidence=0.95)

    conflicts = brain.detect_contradictions()
    assert len(conflicts) >= 1
    c = next(x for x in conflicts if "react" in x["topic"])
    assert c["nature"] == "direct_negation"

    brain.resolve_contradiction(c, auto_supersede=True)
    assert brain.store.get(m1.id).status == MemoryStatus.SUPERSEDED.value
    assert brain.store.get(m2.id).status == MemoryStatus.ACTIVE.value


def test_brain_supersede_primitive(brain):
    m1 = brain.store.add("Project TURNOVER is in private stealth alpha.")
    res = brain.supersede(m1.id, "Project TURNOVER is now in public beta testing!")

    assert res["ok"] is True
    assert res["old_id"] == m1.id

    old_mem = brain.store.get(m1.id)
    assert old_mem.status == MemoryStatus.SUPERSEDED.value
