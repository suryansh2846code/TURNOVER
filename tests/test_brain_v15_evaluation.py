"""Evaluation Dataset and Quality Metrics Suite for Brain v1.5.

Evaluates recall precision, temporal correctness, open loop retrieval,
provenance completeness, and deduplication stability against Section 38/39 requirements.
"""
import tempfile
import pytest

from lodestone.brain import Brain
from lodestone.core.models import MemoryStatus, MemoryType, OpenLoopPriority
from lodestone.core.store import MemoryStore


@pytest.fixture
def eval_brain():
    db_file = tempfile.mktemp(suffix=".db")
    b = Brain(store=MemoryStore(db_path=db_file))

    # Populate synthetic evaluation dataset (Section 38)
    # 1. UI preference
    b.remember(
        "User prefers clean, minimal interfaces with high contrast and no clutter.",
        title="UI Preference",
        memory_type=MemoryType.PREFERENCE.value,
        importance=0.9,
    )
    # 2. Project
    p_id = b.graph.upsert_entity("TURNOVER", type="project", summary="Local-first personal AI workspace")
    # 3. Person
    u_id = b.graph.upsert_entity("Ekta", type="person", summary="Core collaborator on TURNOVER")
    b.graph.add_relation(u_id, "collaborates_on", p_id, "Ekta collaborates on TURNOVER launch")

    # 4. Open loop / commitment
    b.create_open_loop(
        "Deploy production build to staging for validation",
        priority=OpenLoopPriority.HIGH.value,
        related_project="TURNOVER",
        due_at="2026-09-15",
    )

    # 5. Historical preference vs Current preference (Section 38)
    m_old = b.ingest(
        "User used React heavily in 2025 for web apps and frontend stack.",
        source="chat",
        kind="preference",
        valid_from="2025-01-01",
        valid_until="2026-01-01",
        status=MemoryStatus.SUPERSEDED.value,
    )
    m_new = b.ingest(
        "User switched to Vanilla JS and web standards in 2026 for frontend stack.",
        source="chat",
        kind="preference",
        valid_from="2026-01-01",
        status=MemoryStatus.ACTIVE.value,
    )

    return b


def test_eval_suite_precision_and_relevance(eval_brain):
    # Query 1: "What do I prefer in UI?"
    r1 = eval_brain.recall("What do I prefer in UI?")
    assert "minimal" in r1["context"].lower() or any("minimal" in m["text"].lower() for m in r1["memory_hits"])

    # Query 2: "What am I working on?"
    r2 = eval_brain.recall("What am I working on?")
    assert "turnover" in r2["context"].lower() or any("turnover" in e["name"].lower() for e in r2["entities"])

    # Query 3: "What still needs to be done?"
    r3 = eval_brain.recall("What still needs to be done?")
    assert any("deploy" in l["description"].lower() for l in r3["open_loops"])

    # Query 4: "Who is related to this project?"
    r4 = eval_brain.recall("Who is related to project TURNOVER?")
    assert "ekta" in r4["context"].lower() or any("ekta" in e["name"].lower() for e in r4["entities"])


def test_eval_historical_correctness(eval_brain):
    # Present query: current stack must win!
    r_curr = eval_brain.recall("What is my current frontend stack?")
    top_hit = r_curr["memory_hits"][0]
    assert "vanilla js" in top_hit["text"].lower()
    assert top_hit["status"] == MemoryStatus.ACTIVE.value

    # Historical query: old stack must surface!
    r_hist = eval_brain.recall("What did I previously use in 2025?")
    assert any("react" in m["text"].lower() for m in r_hist["memory_hits"])


def test_eval_provenance_and_deduplication(eval_brain):
    # 1. 100% Provenance check for all memories
    mems = eval_brain.store.list()
    assert len(mems) > 0
    for m in mems:
        assert m.source is not None and len(m.source) > 0
        assert m.created_at is not None

    # 2. Repeated ingestion of exact same content produces 0 duplicate memories
    initial_count = eval_brain.store.count()
    eval_brain.ingest("User prefers clean, minimal interfaces with high contrast and no clutter.", title="UI Preference")
    eval_brain.ingest("User prefers clean, minimal interfaces with high contrast and no clutter.", title="UI Preference")
    assert eval_brain.store.count() == initial_count


def test_eval_quality_metrics_runner(eval_brain):
    metrics = eval_brain.evaluate_quality()
    assert metrics["cases_evaluated"] >= 2
    assert metrics["recall_precision"] >= 0.90
    assert metrics["provenance_coverage"] == 1.0
