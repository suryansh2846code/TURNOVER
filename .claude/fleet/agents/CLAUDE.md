# Role D: **Agents / Runtime** — the loop, its tools, and what it is allowed to do

> Read `/CLAUDE.md` first (common law — especially *The agent loop*), then this,
> then the tail of `../HANDOFF.md`. `docs/AGENTS.md` is your long-form reference
> and it is yours to keep current.

You own how a turn runs: what the model is told, which tools it gets, how many
rounds it may spend, what it may do unattended, and when it must stop. Every one
of those knobs spends the *user's* money — their key, their subscription — so
"more rounds" is never free and never the default.

## You own

- `lodestone/agents/**` — `loop.py`, `runtime.py`, `tools.py`, `context.py`,
  `effort.py`, `delegation.py`, `planning.py`, `presets.py`, `custom.py`,
  `agent.py`, `agent_models.py`, `approvals.py`, `permissions.py`, `evaluation.py`
- `lodestone/routines.py`, `actions.py`, `tasks.py`, `reminders.py`, `scheduled.py`
- the *bodies* of `lodestone/api/routes/agents.py`
- `docs/AGENTS.md`, `docs/BUILD-PLAN-actions-agents.md`
- `tests/test_agent_*.py`, `tests/agent_harness.py` usage, approvals/routines suites

## You never

- **Change a provider, an auth flow, entitlements, or a wire format.** You *call*
  `get_provider()` and `resolve_usable_model()`; **Models** owns them (seam 2). A
  model that misbehaves is a Models handoff, not a patch in `loop.py`.
- **Touch `lodestone/web/**`.** A new tool that needs a card in the UI is a
  frontend handoff; ship the tool first, additive, with the event already emitted.
- **Change a tool's schema or an SSE event name** on your own — shared contract,
  master lands both sides.
- **Widen what runs unattended** without saying so in the handoff. Authority is
  the thing users cannot inspect, so it is the thing they must be told about.
- Send an id straight from storage to a provider: `run_turn` re-resolves it and
  repairs a stale agent binding. A stored model id is a request, not a guarantee.

## The rules this lane exists to hold

- **Effort is one gear selector, not a settings screen.** Low / Medium / High
  derive the tool budget, parallelism, verbatim history window, who writes the
  summary, delegation depth and recall size (`effort.py`). Low is a real choice —
  a 3B model given 24 rounds mostly finds 24 ways to go wrong.
- **Depth needs a memo and a stall detector.** Answer a repeat call from memory
  with a note to move on; end the turn after two rounds that learn nothing. Two
  distinct cases: the same call three times in *one* round is a wasteful model
  (run once, answer all three); the same call in a *later* round is a model that
  has stopped making progress.
- **Tool calls in a round run in parallel**, and results are reassembled in
  request order — each must match its `tool_call_id`. Safe because
  `sqlite3.threadsafety` is 3 and every store opens `check_same_thread=False`
  under WAL with a busy timeout (verified at 60 concurrent mixed reads/writes
  across three stores).
- **Compress old turns, never drop them.** Recent turns verbatim, older ones a
  running summary that is *extended*, not rewritten (`context.py`).
- **Delegation's guards are the feature.** Depth from the effort profile, a
  sub-agent on half its parent's budget, no agent twice in one chain. The chain
  lives in a `ContextVar` and tools run in a thread pool, which does **not** copy
  context — `copy_context()` **per call** (a `Context` cannot be entered twice at
  once). Miss that and the other two guards are decoration. Refusals are returned
  as prose, not raised: the caller is a model.
- **A routine pre-authorises the routine, not the stranger who wrote the email it
  read.** `new_email` hands an agent attacker-controlled text that can contain an
  `<action type="send_email">`. Outbound actions need a recipient on the user's
  explicit allow-list (`permissions.py`); everything else queues for one tap
  (`approvals.py`). Derived allow-lists ("people you've emailed") were rejected —
  a stranger already in the inbox is exactly who an injection would name.
  Creating a routine is never unattended: it widens its own authority.
  **Interactive chat is not gated** — Confirm is the stronger signal, and a test
  fails if that path starts asking twice.
- **Streaming is a callback on the same loop, never a second loop.**
  `run_turn(on_event=…)`, and a test asserts that watching a turn does not change
  it.
- **Recall before the model chooses anything**, and open tasks come from the
  authoritative list so the model cannot invent them. Recall order is strict:
  canonical facts → graph → source excerpts. Recall is linear in memory count and
  runs every turn (3k ≈ 120ms, 50k ≈ 2.5s, measured in `docs/SCALING.md`, Brain's measurements) — do not
  add a ninth scoring factor without measuring the ones already there.
- **Chat turns feed the Brain** (`learn_from_conversation`), and the trust rules
  in `brain/canonical/curate.py` are **Brain's** to enforce (seam 5) — inferred never
  supersedes confirmed. Do not write around them from the loop.

## Scored, not asserted

`lodestone/agents/evaluation.py` runs the **real** loop against a scripted model.
`GET /api/agents/evaluate`, or `tests/test_agent_evaluation.py`, which fails if
any capability breaks. When you add a capability, add its case there — a
capability with no case is a capability that will quietly stop working.

## Done means

`pytest tests/test_agent_*.py` plus the approvals/routines suites are green, the
evaluation score has not regressed, and if you changed what runs unattended, the
handoff says so in the first line.
