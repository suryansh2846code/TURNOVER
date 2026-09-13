# `lodestone/agents/` — the loop

The turn loop, tools, effort, delegation, planning, approvals, permissions.

- Effort is one gear selector (Low/Medium/High), not a settings screen — it
  derives every budget at once, and it spends the *user's* money.
- Tool calls in a round run in parallel; results reassemble by `tool_call_id`.
  Delegation guards live in a `ContextVar`, so it is one `copy_context()` **per
  call**.
- Compress old turns, never drop them.
- A routine pre-authorises the routine, not the stranger who wrote the email it
  read. Outbound actions need a recipient on the explicit allow-list; everything
  else queues for one tap. Interactive chat is deliberately not gated.
- Every new capability gets a case in `evaluation.py`.

Providers and entitlements belong to `../models/`; recall order belongs to
`../brain/`. Rules: [`/CLAUDE.md`](../../CLAUDE.md).
