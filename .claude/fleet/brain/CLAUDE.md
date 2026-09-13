# Role E: **Brain / Memory** — one model of the user, layered, never duplicated

> Read `/CLAUDE.md` first, then `docs/BRAIN-V1.5.md` (the specification) and
> `docs/SCALING.md` (the measurements), then this, then `../HANDOFF.md`.

Four layers, and the distinction between them is the architecture: **raw memories**
(thousands of emails, in `lodestone.db`) → **the knowledge graph** → **canonical
facts** (curated, source-backed, in `brain.db`) → **generated projections**
(`brain-export/` markdown+JSON). The projection is never a second source of truth,
and raw email must never become "memory" in the canonical sense.

## You own

`lodestone/brain/**` (incl. `canonical/**` — `db`, `store`, `redact`, `extract`,
`curate`, `freshness`, `recall`, `export`, `evaluation`, `service`),
`lodestone/core/**` (store, db, chunking, embeddings, dateparse),
`docs/BRAIN-V1.5.md`, `docs/SCALING.md`, `scripts/benchmark_*.py`, and the brain /
core test suites.

## You never

- **Introduce a second source of truth.** A new table that restates what claims
  already hold, or a cache that outlives its source, is the failure this layering
  exists to prevent.
- **UPDATE a claim.** Claims are **append-only**: a change supersedes the prior
  version and writes a Timeline event. History is the product.
- **Let the model decide trust.** The rules live in `curate.py`, in code:
  confirmed can supersede inferred, **inferred never supersedes confirmed**;
  replacing a time-sensitive current claim requires a *newer* `source_timestamp`;
  tentative language becomes an `open` claim, never a current one; every accepted
  claim retains evidence; connector-sourced inferred facts go to the review queue —
  only `manual` and `chat` are high-trust.
- **Change recall order.** Strict: **canonical facts → graph → source excerpts**.
  `Brain.recall()` prepends the canonical block and swallows its own failures so
  curation can never break plain retrieval. The injection point belongs to Agents
  (seam 5) — do not reach into `runtime.py`.
- **Lower confidence by age.** Freshness ages only *time-sensitive current* claims.
- **Gate the graph on a source allowlist.** Enrichment is content-based and
  general — `clean_for_extraction()` then `is_graphable()`, LLM extraction when
  available, heuristic offline. It must work for a connector nobody has written yet.
- **Skip redaction.** Secrets are masked **before** extraction, on every ingest
  path (`[REDACTED_KEY]`, `[REDACTED_PASSWORD]`, `[REDACTED_SECRET]`).

## Load-bearing details

- **`"key" in row` on a `sqlite3.Row` tests the VALUES, not the keys.** Every
  optional-column guard in the graph store was written that way, so entity
  importance and confidence silently stayed at defaults — measured stuck at 0.55
  where it should have reached 0.7. Use `row.keys()`. `SIM118`/`SIM401` are
  disabled in `pyproject.toml` for this reason; re-enabling either brings the bug
  back.
- **Recall cost is the known ceiling.** `store.search()` is linear in memory count
  (~0.05 ms each) and runs on **every** agent turn: 3k ≈ 120 ms, 10k ≈ 430 ms,
  50k ≈ 2.5 s. 95% is the eight-factor Python scoring loop; the vector matmul is
  0.1%. **Do not reach for an ANN index** — it optimises the 0.1%. A top-K
  pre-filter before the loop measured **25–33× faster** (50k: 2.3 s → 70 ms) as a
  contained change to one function, and is deliberately deferred pending a product
  decision (`docs/AUDIT.md` A6, `docs/ROADMAP.md`). Reproduce with
  `scripts/benchmark_recall.py` before and after anything you change here.
- **The enrich queue's recent-N cap is the dominant cost control.** Bulk sources
  are capped to their most-recent N (default 100, `meta.enrich_cap`, 0 = unlimited)
  via a window function in `list_ungraphed`/`count_ungraphed`; high-signal sources
  (`notes`, `agent`, `manual`, `notion`, `gcal`) always enrich in full. The free
  heuristic pass is **not** capped, so nothing is orphaned.
- **The LLM enrich is a server-side job** (`start_enrich`/`stop_enrich`/
  `enrich_status`) so a frontend refresh reconnects instead of killing it, and it
  can run on a *different, cheaper* model than chat.
- **Open loops are a table, not a vibe** — commitments and follow-ups with
  priority, due date, links and lifecycle statuses, fed into prompt auto-recall.
- `detect_conflicts()` / `resolve_conflict()` are non-destructive: superseding
  preserves the full history when a user changes their mind.

## Done means

`pytest tests/test_brain_v15_*.py tests/test_canonical_brain.py tests/test_core.py`
green, then the full sequence — plus `scripts/benchmark_recall.py` if you touched
scoring, with the before/after numbers in your handoff. Recall is on the critical
path of every single turn; a change here with no measurement is a guess.
