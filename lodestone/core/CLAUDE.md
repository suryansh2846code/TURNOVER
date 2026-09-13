# `lodestone/core/` — store, DB, chunking, embeddings, dates

`store.search()` runs on **every** agent turn and is linear in memory count
(~0.05 ms each): 3k ≈ 120 ms, 10k ≈ 430 ms, 50k ≈ 2.5 s. 95% of that is the
eight-factor Python scoring loop and 0.1% is the vector matmul — so an ANN index
would optimise the wrong thing.

Measure with `scripts/benchmark_recall.py` before and after touching the scoring.
Analysis: [`docs/SCALING.md`](../../docs/SCALING.md).

`_migrate` is additive `ALTER TABLE` only, and idempotent.
