# You are in the **api** role's territory

Rules: [`.claude/fleet/api/CLAUDE.md`](../../.claude/fleet/api/CLAUDE.md) ·
common law: [`/CLAUDE.md`](../../CLAUDE.md) ·
who owns what: the ownership map in `/CLAUDE.md`.

`app.py` is the composition root; routes live in `routes/` and mount from `ALL_ROUTERS`. The handler **bodies** in `routes/agents.py` belong to the **Agents** role (seam 1). Endpoint shapes are cross-layer contracts — the Architect lands changes to them, and `tests/api_surface.json` pins the surface.

**No rules live in this file.** A duplicated rule drifts, and the copy that drifts
is always the one you read. If you are another role: do not edit files here — write
a handoff in `.claude/fleet/HANDOFF.md`.
