# `lodestone/agents/` — the loop

The turn loop, tools, effort, delegation, planning, grounding, approvals,
permissions — and `library.py`, which is what Lodestone *offers*.

- **The library is not the roster.** `library.py` holds every agent that ships;
  the roster is the few the user took on, and `list_agents()` returns only
  those. An agent nobody picked is one nobody opens. A template that leaves the
  roster keeps its conversation — removing is not deleting.

- Effort is one gear selector (Low/Medium/High), not a settings screen — it
  derives every budget at once, and it spends the *user's* money. It caps
  **tokens** as well as rounds, on one ledger shared down the delegation chain,
  so three agents spend one budget between them.
- **An agent is only told what it can do.** The system prompt is assembled from
  blocks in `prompt.py`; `Agent.actions` selects the proposal protocols. An
  agent with no actions has no way to claim it sent anything.
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
- **An agent's conversation is its own.** A delegated turn runs `persist=False`
  — no history in, nothing written out, no learning — because the "user" of that
  turn is another agent. The brain stays shared; the chat does not.
- A routine pre-authorises the routine, not the stranger who wrote the email it
  read. Outbound actions need a recipient on the explicit allow-list; everything
  else queues for one tap. Interactive chat is deliberately not gated.
- Every new capability gets a case in `evaluation.py`.

Providers and entitlements belong to `../models/`; recall order belongs to
`../brain/`. Rules: [`/CLAUDE.md`](../../CLAUDE.md).
