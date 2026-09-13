# The Lodestone engineering fleet

Eight specialised Claude sessions build this app in parallel, one per git
worktree, plus temporary custom specialists. This directory holds each role's
rules. One file per role, one owner per path.

| role | rules | owns, in one line | worktree · branch |
|---|---|---|---|
| **A · Architect** | [`architect/`](architect/CLAUDE.md) | decomposition, contracts, review, docs, `main` | `lodestone` · `main` |
| **B · Frontend** | [`frontend/`](frontend/CLAUDE.md) | `lodestone/web/**` — chat, agents, drawer, onboarding, streaming UI | `../lodestone-frontend` · `agent/frontend` |
| **C · API** | [`api/`](api/CLAUDE.md) | routes, schemas, security, concurrency, composition, runtime plumbing | `../lodestone-api` · `agent/api` |
| **D · Agents** | [`agents/`](agents/CLAUDE.md) | the loop, tools, delegation, planning, approvals, effort | `../lodestone-agents` · `agent/agents` |
| **E · Brain** | [`brain/`](brain/CLAUDE.md) | memory, recall, graph, canonical facts, enrichment | `../lodestone-brain` · `agent/brain` |
| **F · Models** | [`models/`](models/CLAUDE.md) | providers, discovery, entitlements, auth flows, vendor CLIs | `../lodestone-models` · `agent/models` |
| **G · Connectors** | [`connectors/`](connectors/CLAUDE.md) | sources, registry, ingestion, MCP | `../lodestone-connectors` · `agent/connectors` |
| **H · QA** | [`qa/`](qa/CLAUDE.md) | repros, regression tests, `docs/AUDIT.md` | `../lodestone-qa` · `agent/qa` |
| **— · Desktop** *(dormant)* | [`desktop/`](desktop/CLAUDE.md) | `desktop.py`, `hud.py`, packaging, the `.dmg` | activated per task |
| **— · Custom** *(temporary)* | [`_template/`](_template/CLAUDE.md) | whatever a task scopes, then dissolved | `../lodestone-<name>` · `agent/custom/<name>` |

Also here:

- **[`HANDOFF.md`](HANDOFF.md)** — the append-only log where work crosses roles.
  **Read its tail before you start**; it is how you learn what changed under you.
- **[`_template/CLAUDE.md`](_template/CLAUDE.md)** — the scoped role definition to
  fill in for a custom specialist, or to copy when the Architect adds a permanent
  role (procedure: `/CLAUDE.md` → *Adding a permanent role*).
- **`locks/`** — transient "I am editing this right now" claims (gitignored;
  courtesy, not enforcement).

## Reading order, every session

1. **`/CLAUDE.md`** — common law: product rules, the model-availability doctrine,
   the agent-loop invariants, the ownership map, the six seams, the ten rules of
   parallel work.
2. **your role's file here** — what you own, what you must not touch, the traps
   your subsystem has already paid for.
3. **the tail of `HANDOFF.md`** — anything another role has handed you.

## Running tests in your worktree

One shared venv; `PYTHONPATH` makes imports resolve to *your* copy:

```bash
cd ../lodestone-<role>
PYTHONPATH="$PWD" /Users/suryanshsingh/workspace/lodestone/.venv/bin/python -m pytest <slice> -q
```

Do not symlink `.venv` into a worktree and do not `pip install -e .` there — both
reintroduce the ambiguity about which checkout you are testing.

The code directories a role owns also carry a short pointer `CLAUDE.md`
(e.g. `lodestone/web/CLAUDE.md`), so opening a file there loads the role's rules
automatically. Pointers hold no rules of their own: a duplicated rule drifts, and
the copy that drifts is always the one you read.
