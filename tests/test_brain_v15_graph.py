"""Tests for Brain v1.5 Knowledge Graph:
Entity types, aliases, relation confidence, temporal bounds, related entity traversal, and quality pruning.
"""
import tempfile
import pytest

from lodestone.brain import Brain
from lodestone.core.store import MemoryStore


@pytest.fixture
def store():
    db_file = tempfile.mktemp(suffix=".db")
    return MemoryStore(db_path=db_file)


@pytest.fixture
def brain(store):
    return Brain(store=store)


def test_entity_creation_with_aliases_and_types(brain):
    # Upsert entity with aliases
    eid = brain.graph.upsert_entity(
        "Suryansh",
        type="person",
        summary="Founder of TURNOVER",
        aliases=["suryanshsingh", "suryansh2846"],
        confidence=0.95,
        importance=0.9,
    )
    assert eid

    # Get entity
    ent = brain.get_entity(eid)
    assert ent is not None
    assert ent["name"] == "Suryansh"
    assert ent["type"] == "person"
    assert "suryanshsingh" in ent["aliases"]
    assert ent["confidence"] == 0.95
    assert ent["importance"] == 0.9

    # Alias match query
    matches = brain.graph.match_entities("who is suryansh2846?")
    assert len(matches) >= 1
    assert matches[0]["id"] == eid


def test_relationships_with_confidence_and_temporal_bounds(brain):
    e1 = brain.graph.upsert_entity("Suryansh", type="person")
    e2 = brain.graph.upsert_entity("TURNOVER", type="project")

    # Add relation
    brain.graph.add_relation(
        subject_id=e1,
        predicate="works_on",
        object_id=e2,
        fact="Suryansh builds and leads TURNOVER",
        confidence=0.98,
        source="conversation",
        valid_from="2026-01-01",
    )

    facts = brain.graph.facts_for(e1)
    assert len(facts) >= 1
    assert "TURNOVER" in facts[0]

    # Test get_related
    related = brain.get_related(e1)
    assert len(related) >= 1
    assert related[0]["target_name"] == "TURNOVER"
    assert related[0]["predicate"] == "works_on"
    assert related[0]["confidence"] == 0.98


def test_noise_filtering_and_pruning(brain):
    # Noise words should be rejected early
    bad1 = brain.graph.upsert_entity("thing", type="thing")
    assert bad1 == ""

    bad2 = brain.graph.upsert_entity("today", type="thing")
    assert bad2 == ""

    # Good entity is kept
    good = brain.graph.upsert_entity("Algorand", type="technology")
    assert good != ""

    pruned = brain.graph.prune_noise()
    assert pruned["removed_entities"] == 0  # no junk was saved
