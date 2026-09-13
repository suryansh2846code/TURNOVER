# You are in the **frontend** role's territory

Rules: [`.claude/fleet/frontend/CLAUDE.md`](../../.claude/fleet/frontend/CLAUDE.md) ·
common law: [`/CLAUDE.md`](../../CLAUDE.md) ·
who owns what: the ownership map in `/CLAUDE.md`.

Vanilla JS, no build step. Cmd+R reloads the frontend only. Relative API paths, never a host or port. If you add a render path or a click handler, **execute it in a test** (`tests/js/`) — `node --check` and source-order assertions both pass while these are broken.

**No rules live in this file.** A duplicated rule drifts, and the copy that drifts
is always the one you read. If you are another role: do not edit files here — write
a handoff in `.claude/fleet/HANDOFF.md`.
