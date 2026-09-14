# `lodestone/agents/` — the loop

The turn loop, tools, effort, delegation, planning, grounding, approvals,
permissions.

- Effort is one gear selector (Low/Medium/High), not a settings screen — it
  derives every budget at once, and it spends the *user's* money.
- Tool calls in a round run in parallel; results reassemble by `tool_call_id`.
  Delegation guards live in a `ContextVar`, so it is one `copy_context()` **per
  call**.
- Compress old turns, never drop them.
- **Anything the user starts, they can stop.** A turn carries a stop event
  (`cancellation.py`); the loop reads it between rounds, before each tool, and
  while a stream is arriving. A stopped turn keeps the half-written answer and
  spends nothing more — not one wrap-up call, not the post-turn learning — and
  its delegated sub-agents stop with it.
- **Anything we add to the model's input, we take back out before a tool reads
  it.** The date note goes in with `grounding.prefixed` and comes out with
  `grounding.strip_arguments` — a model copies its own input, and a date inside
  `search_brain`'s query is read by recall as a filter.
- A routine pre-authorises the routine, not the stranger who wrote the email it
  read. Outbound actions need a recipient on the explicit allow-list; everything
  else queues for one tap. Interactive chat is deliberately not gated.
- Every new capability gets a case in `evaluation.py`.

Providers and entitlements belong to `../models/`; recall order belongs to
`../brain/`. Rules: [`/CLAUDE.md`](../../CLAUDE.md).
