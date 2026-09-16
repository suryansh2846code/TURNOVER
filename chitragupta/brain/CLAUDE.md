# `chitragupta/brain/` — memory, graph, canonical facts

Raw index + knowledge graph in `chitragupta.db`; the curated canonical brain in its
own `brain.db`; `brain-export/` is a **generated projection, never a second
source of truth**.

- Trust rules live in `canonical/curate.py`, in code, never left to the model:
  confirmed can supersede inferred and never the reverse, replacing a
  time-sensitive claim needs a newer `source_timestamp`, tentative language opens
  a claim rather than making it current, and every accepted claim keeps evidence.
- Claims are **append-only** — a change supersedes, never `UPDATE`s.
- Recall order is strict: canonical facts → graph → source excerpts.
- Graph enrichment is content-based and general. **Never gate it on a
  connector-name allowlist.**
- `"key" in row` on a `sqlite3.Row` tests the **values**, not the keys. Use
  `row.keys()`. `SIM118`/`SIM401` are disabled for exactly this reason.

Rules: [`/CLAUDE.md`](../../CLAUDE.md) · spec: [`docs/BRAIN-V1.5.md`](../../docs/BRAIN-V1.5.md).
