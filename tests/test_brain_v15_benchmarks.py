"""Performance and Latency Benchmarks for Brain v1.5."""
import tempfile
import time
import pytest

from lodestone.brain import Brain
from lodestone.core.models import MemoryType
from lodestone.core.store import MemoryStore


def test_benchmark_ingestion_and_recall_latency():
    db_file = tempfile.mktemp(suffix=".db")
    store = MemoryStore(db_path=db_file)
    brain = Brain(store=store)

    # 1. Ingestion latency benchmark (100 distinct memories)
    start_ingest = time.perf_counter()
    for i in range(100):
        store.add(
            f"Fact number {i}: User preference item {i} regarding deployment, testing, and performance.",
            source="benchmark",
            memory_type=MemoryType.SEMANTIC.value,
            importance=0.5 + (i % 5) * 0.1,
            confidence=0.8,
        )
    ingest_duration = time.perf_counter() - start_ingest
    avg_ingest_ms = (ingest_duration / 100) * 1000

    assert store.count() == 100
    # Ingestion should average under 50ms per memory with offline embedding
    assert avg_ingest_ms < 50.0

    # 2. Recall latency benchmark (hybrid retrieval with explainability)
    start_recall = time.perf_counter()
    num_queries = 20
    for q in range(num_queries):
        hits = store.search(f"preference item {q}", limit=8)
        assert len(hits) >= 1
    recall_duration = time.perf_counter() - start_recall
    avg_recall_ms = (recall_duration / num_queries) * 1000

    # Search should be fast (< 25ms per query for 100 in-memory items)
    assert avg_recall_ms < 25.0

    # 3. Open loops latency
    start_loop = time.perf_counter()
    for j in range(50):
        brain.create_open_loop(f"Task loop {j} for milestone execution", related_project="TURNOVER")
    loops = brain.get_open_loops(related_project="TURNOVER")
    loop_duration = time.perf_counter() - start_loop

    assert len(loops) == 50
    assert loop_duration < 1.0
