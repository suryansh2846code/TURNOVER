# You are in the **connectors** role's territory

Rules: [`.claude/fleet/connectors/CLAUDE.md`](../../.claude/fleet/connectors/CLAUDE.md) ·
common law: [`/CLAUDE.md`](../../CLAUDE.md) ·
who owns what: the ownership map in `/CLAUDE.md`.

One class per source, registered in `__init__.py::REGISTRY`. Sync idempotently, redact on ingest, survive a crash without taking the sync down, stay cancellable — and never gate graph enrichment on a connector name.

**No rules live in this file.** A duplicated rule drifts, and the copy that drifts
is always the one you read. If you are another role: do not edit files here — write
a handoff in `.claude/fleet/HANDOFF.md`.
