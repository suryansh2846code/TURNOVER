"""Benchmark suite for Brain v1.5 verification gate (Section 12).

Measures:
- Ingestion (end-to-end)
- Embedding latency
- Database write latency
- Recall (cold cache vs warm cache)
- Graph lookup latency
- Deduplication latency
Across 1,000 and 10,000 memories, reporting p50, p95, p99.
"""
import time
import tempfile
import numpy as np
from pathlib import Path
from lodestone.brain.brain import Brain
from lodestone.core.store import MemoryStore
from lodestone.core.embeddings import HashEmbedder

def percentile(vals, p):
    return float(np.percentile(vals, p))

def run_benchmarks(n_memories=1000, embedder_type="hash"):
    print(f"\n==================================================================")
    print(f"RUNNING BENCHMARKS: {n_memories:,} memories | embedder: {embedder_type}")
    print(f"==================================================================")
    
    tmp = tempfile.mktemp(suffix=".db")
    embedder = HashEmbedder() if "hash" in embedder_type else None
    store = MemoryStore(db_path=tmp, embedder=embedder)
    brain = Brain(store=store)

    ingest_times = []
    embed_times = []
    db_write_times = []
    dedup_times = []

    # 1. Ingestion benchmarks
    texts = [
        f"Memory record #{i}: Engineering log discussing subsystem verification, temporal reasoning, and index integrity for personal AI agent worker."
        for i in range(n_memories)
    ]

    for i, t in enumerate(texts):
        # Measure standalone embedding
        t0_emb = time.perf_counter()
        ev = store._embedder.embed_one(t)
        t1_emb = time.perf_counter()
        embed_times.append((t1_emb - t0_emb) * 1000)

        # Measure end-to-end ingestion
        t0 = time.perf_counter()
        res = brain.ingest(t, source="benchmark", kind="fact", title=f"Bench #{i}", build_graph=False)
        t1 = time.perf_counter()
        ingest_times.append((t1 - t0) * 1000)

    # Measure dedup latency on repeated entries
    for i in range(min(200, n_memories)):
        t = texts[i]
        t0 = time.perf_counter()
        res_dup = brain.ingest(t, source="benchmark", kind="fact", title=f"Bench #{i}", build_graph=False)
        t1 = time.perf_counter()
        dedup_times.append((t1 - t0) * 1000)

    # 2. Graph lookup benchmarks
    for i in range(25):
        e_id = brain.graph.upsert_entity(f"Entity_{i}", type="technology", summary=f"Benchmark entity {i}")
        if i > 0:
            brain.graph.add_relation(e_id, "relates_to", f"Entity_{i-1}", "Test link")

    graph_times = []
    for i in range(50):
        t0 = time.perf_counter()
        res_g = brain.graph.match_entities(f"Entity_{i % 25}", limit=5)
        t1 = time.perf_counter()
        graph_times.append((t1 - t0) * 1000)

    # 3. Recall benchmarks: Cold cache vs Warm cache
    # Cold cache query (first run)
    store._vecs = None  # invalidate cache
    store._dirty = True
    t0_cold = time.perf_counter()
    res_cold = brain.recall("subsystem verification and temporal reasoning", limit=5)
    t1_cold = time.perf_counter()
    cold_latency = (t1_cold - t0_cold) * 1000

    # Warm cache queries
    warm_times = []
    queries = [
        "subsystem verification",
        "temporal reasoning",
        "personal AI agent",
        "index integrity",
        "non-existent token query zzz",
    ]
    for q in queries * 20:
        t0 = time.perf_counter()
        r = brain.recall(q, limit=5)
        t1 = time.perf_counter()
        warm_times.append((t1 - t0) * 1000)

    # Report numbers
    print(f"INGESTION (End-to-End, per record):")
    print(f"  p50: {percentile(ingest_times, 50):.3f} ms | p95: {percentile(ingest_times, 95):.3f} ms | p99: {percentile(ingest_times, 99):.3f} ms")
    
    print(f"EMBEDDING (per record):")
    print(f"  p50: {percentile(embed_times, 50):.3f} ms | p95: {percentile(embed_times, 95):.3f} ms | p99: {percentile(embed_times, 99):.3f} ms")

    print(f"DEDUPLICATION (per check):")
    print(f"  p50: {percentile(dedup_times, 50):.3f} ms | p95: {percentile(dedup_times, 95):.3f} ms | p99: {percentile(dedup_times, 99):.3f} ms")

    print(f"GRAPH LOOKUP:")
    print(f"  p50: {percentile(graph_times, 50):.3f} ms | p95: {percentile(graph_times, 95):.3f} ms | p99: {percentile(graph_times, 99):.3f} ms")

    print(f"RECALL (Cold Cache, first load):")
    print(f"  latency: {cold_latency:.3f} ms")

    print(f"RECALL (Warm Cache, in-memory vecs):")
    print(f"  p50: {percentile(warm_times, 50):.3f} ms | p95: {percentile(warm_times, 95):.3f} ms | p99: {percentile(warm_times, 99):.3f} ms")

    return {
        "n_memories": n_memories,
        "embedder": embedder_type,
        "ingest_p50": percentile(ingest_times, 50),
        "ingest_p95": percentile(ingest_times, 95),
        "ingest_p99": percentile(ingest_times, 99),
        "embed_p50": percentile(embed_times, 50),
        "dedup_p50": percentile(dedup_times, 50),
        "graph_p50": percentile(graph_times, 50),
        "cold_recall": cold_latency,
        "warm_recall_p50": percentile(warm_times, 50),
        "warm_recall_p95": percentile(warm_times, 95),
        "warm_recall_p99": percentile(warm_times, 99),
    }

if __name__ == "__main__":
    b1k_hash = run_benchmarks(1000, embedder_type="hash (offline mock)")
    b10k_hash = run_benchmarks(10000, embedder_type="hash (offline mock)")
    b100_real = run_benchmarks(100, embedder_type="real (bge-small-en-v1.5)")
