# You are in the **brain** role's territory

Rules: [`.claude/fleet/brain/CLAUDE.md`](../../.claude/fleet/brain/CLAUDE.md) ·
common law: [`/CLAUDE.md`](../../CLAUDE.md) ·
who owns what: the ownership map in `/CLAUDE.md`.

Store, DB, chunking, embeddings, date parsing. `store.search()` runs on **every** agent turn and is linear in memory count — measure with `scripts/benchmark_recall.py` before and after touching its scoring (`docs/SCALING.md`).

**No rules live in this file.** A duplicated rule drifts, and the copy that drifts
is always the one you read. If you are another role: do not edit files here — write
a handoff in `.claude/fleet/HANDOFF.md`.
