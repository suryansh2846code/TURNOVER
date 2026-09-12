#!/usr/bin/env python
"""Reproduce the numbers in docs/SCALING.md.

Measures recall latency against the real MemoryStore.search() across memory
counts, and profiles where the time goes.

    ./.venv/bin/python scripts/benchmark_recall.py            # latency curve
    ./.venv/bin/python scripts/benchmark_recall.py --profile  # stage breakdown
"""
import argparse
import os
import random
import statistics
import sys
import tempfile
import time

os.environ.setdefault("LODESTONE_EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("LODESTONE_HOME", tempfile.mkdtemp(prefix="lodestone-bench-"))

from lodestone.core.store import MemoryStore  # noqa: E402

WORDS = ("project launch deadline invoice meeting notes review client budget travel "
         "design api database migration release feedback roadmap hiring contract "
         "quarterly revenue metrics onboarding retro incident latency pricing").split()


def build(n: int, seed: int = 7) -> tuple[MemoryStore, str]:
    random.seed(seed)
    path = os.path.join(tempfile.mkdtemp(), "bench.db")
    store = MemoryStore(path)
    store.add_many([{
        "text": " ".join(random.choices(WORDS, k=60)),
        "title": " ".join(random.choices(WORDS, k=5)),
        "source": random.choice(["gmail", "gdrive", "notes", "gcal"]),
        "uri": f"doc://{i}",
    } for i in range(n)])
    store.search("warm the vector cache")
    return store, path


def latency_curve(sizes: list[int], queries: int = 25) -> None:
    print(f"{'memories':>9} {'db':>8} {'recall p50':>12} {'p95':>9} {'per-memory':>12}")
    for n in sizes:
        store, path = build(n)
        lat = []
        for _ in range(queries):
            q = " ".join(random.choices(WORDS, k=4))
            t = time.perf_counter()
            store.search(q, limit=8)
            lat.append((time.perf_counter() - t) * 1000)
        p50 = statistics.median(lat)
        print(f"{n:>9,} {os.path.getsize(path)/1e6:>7.1f}M {p50:>11.1f}ms "
              f"{sorted(lat)[int(len(lat)*0.95)-1]:>8.1f}ms {p50/n*1000:>11.3f}us")


def profile(n: int = 25_000) -> None:
    store, _ = build(n)
    t = time.perf_counter()
    rows = store._conn.execute(
        "SELECT id, text, title, source, memory_type, event_date, valid_from, "
        "valid_until, importance, confidence, reinforcement_count, status, "
        "created_at, updated_at FROM memories WHERE status != 'retracted'").fetchall()
    sql = (time.perf_counter() - t) * 1000

    qv = store._embedder.embed_query("project deadline")
    t = time.perf_counter()
    _ = store._vecs @ qv
    matmul = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    store.search("project deadline", limit=8)
    total = (time.perf_counter() - t) * 1000

    print(f"  {n:,} memories · vectors {store._vecs.shape} "
          f"({store._vecs.nbytes/1e6:.1f} MB resident) · {len(rows):,} rows scanned\n")
    for label, ms in (("SQL full scan", sql), ("numpy matmul", matmul),
                      ("Python scoring loop", total - sql - matmul)):
        print(f"  {label:<22}{ms:>9.1f} ms  ({ms/total*100:>5.1f}%)")
    print(f"  {'total':<22}{total:>9.1f} ms")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", action="store_true", help="stage breakdown instead of the curve")
    ap.add_argument("--sizes", type=int, nargs="+", default=[1_000, 3_000, 10_000, 25_000])
    args = ap.parse_args()
    profile() if args.profile else latency_curve(args.sizes)
