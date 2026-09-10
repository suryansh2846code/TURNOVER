"""Tests for Brain v1.5 Retrieval Engine:
Hybrid ranking, explainability, source weighting, recency, and historical queries.
"""
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


def test_hybrid_ranking_with_explainability(store):
    store.add(
        "TURNOVER is the flagship local-first AI workspace project.",
        importance=0.9,
        confidence=0.95,
        source="chat",
    )
    store.add(
        "A random note about apples and oranges.",
        importance=0.2,
        confidence=0.5,
        source="notes",
    )

    hits = store.search("what is the TURNOVER project?", limit=5)
    assert len(hits) >= 1
    top = hits[0]
    assert "TURNOVER" in top.memory.text
    assert top.score > 0.4

    # Verify explainability object
    assert top.explanation is not None
    assert top.explanation.importance_boost > 0.0
    assert top.explanation.confidence_boost > 0.0
    assert top.explanation.total_score == top.score
    assert len(top.explanation.factors) >= 1


def test_active_preferred_over_superseded_in_current_query(store):
    # Old preference
    old = store.add(
        "User prefers Postgres for all database needs.",
        valid_from="2024-01-01",
        status=MemoryStatus.SUPERSEDED.value,
        valid_until="2026-01-01",
    )
    # Current preference
    current = store.add(
        "User prefers SQLite for local-first storage.",
        valid_from="2026-01-01",
        status=MemoryStatus.ACTIVE.value,
    )

    # Standard present query
    hits = store.search("what database do I prefer?", limit=5)
    assert len(hits) >= 1
    top = hits[0]
    assert top.memory.id == current.id
    assert "SQLite" in top.memory.text


def test_historical_query_surfaces_superseded_memory(store):
    # Old preference
    old = store.add(
        "User previously used React heavily in 2025.",
        valid_from="2025-01-01",
        status=MemoryStatus.SUPERSEDED.value,
        valid_until="2026-01-01",
    )
    # Current preference
    current = store.add(
        "User builds interfaces with Vanilla JavaScript.",
        valid_from="2026-01-01",
        status=MemoryStatus.ACTIVE.value,
    )

    # Historical query containing "previously"
    hits = store.search("what did I previously use for frontend?", limit=5)
    assert any(h.memory.id == old.id for h in hits)
    # Old memory receives historical match boost
    old_hit = next(h for h in hits if h.memory.id == old.id)
    assert "historical_match" in old_hit.explanation.factors


def test_source_weighting_and_preference(store):
    store.add("Meeting scheduled with client about launch.", source="gmail")
    store.add("Meeting schedule and agenda for launch.", source="notes")

    # When prefer contains 'gmail', gmail memory should get boosted
    hits_preferred = store.search("meeting with client", limit=5, prefer=["gmail"])
    assert hits_preferred[0].memory.source == "gmail"
    assert "preferred_source:gmail" in hits_preferred[0].explanation.factors


def test_context_construction_in_brain_recall(brain):
    brain.store.add("Aryan and Jai launched Turnstone in YC W26.", source="manual")
    brain.store.add_open_loop("Review open loop deployment checklist.", related_project="TURNOVER")

    res = brain.recall("what is happening with the launch and Turnstone?")
    assert res["context"]
    assert "RELEVANT MEMORIES" in res["context"] or "CANONICAL FACTS" in res["context"]
    assert len(res["memory_hits"]) >= 1
    assert "explanation" in res["memory_hits"][0]
