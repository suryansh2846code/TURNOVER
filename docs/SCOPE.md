# Lodestone — Full Scope / Backlog

> The complete picture of what's built, what's left, and the order we'll do it.
> **Sequence (your call):** ① harden what we have → ② add new features →
> ③ full UI/UX redesign (you) → ④ landing page.
> Status: 30 Aug 2026. Nothing here is being built yet — this is the map.

---

## ✅ Already built (baseline)
- Agent-first workspace: 4 agents (Inbox · Launch · Research · Personal) + custom agents.
- Knowledge-graph brain: vector memories + entity/relation graph, shared by all agents.
- BYO model: claude-code · ollama · anthropic · openai · openrouter · subscription · mock.
- BGE semantic recall, date-aware retrieval, source overviews, on-demand Drive fetch.
- Connectors (11): files · notes · gmail · gcal · gdrive · notion · imessage ·
  apple_mail · apple_calendar · **linear · github**.
- **Custom API connector** — connect any REST app, no code.
- Actions (confirm-before-execute): send_email · create_event · set_reminder · create_routine.
- Reminders (desktop notifications) · scheduled sending · routines (event + schedule triggers).
- Bundled Google sign-in · in-app secret fields · desktop .app · tester install script.
- Auto-migration versioning · self-healing dedup · continuous background sync.

---

## ① HARDEN WHAT WE HAVE  *(do first — make it best)*

### Reliability
- [ ] Verify **every** connector end-to-end with real data — Notion, Linear, GitHub,
      custom API, Apple Mail/Calendar, iMessage (several built but never run live).
- [ ] claude-code path: just fixed GUI PATH; test reminders/todo flow end-to-end on it.
- [ ] Google token refresh: handle the 7-day testing-mode expiry gracefully in the UI
      (detect, prompt "reconnect", don't fail silently).
- [ ] Small-model tool-calling flakiness (qwen/llama) — grounding helps, not solved.
- [ ] Sync robustness — partial failures, rate limits, timeouts per connector.

### Correctness / data quality
- [ ] Graph/entity dedup + noise audit (recurring theme — keep it clean at scale).
- [ ] Recall quality regression tests (the "ranks the right memory" checks).
- [ ] Date/time parsing edge cases (timezones, "next Tuesday", recurring).

### Feedback & error surfaces
- [ ] Friendly empty states + error messages everywhere (no raw tracebacks to user).
- [ ] Per-connector sync progress + result counts in the UI.
- [ ] Clear "what's connected / what's stale" at a glance.

### Safety & trust
- [ ] Brain **export / backup** (and import) — user owns their data, can move it.
- [ ] Encrypt secrets at rest (currently chmod-600 plaintext JSON).
- [ ] "What leaves my device" transparency panel (cloud model = context leaves; local = not).

### Tests
- [ ] Expand beyond ~6 smoke tests: recall, date parsing, connectors, on-demand
      fetch, dedupe, migrations, actions, custom API.

---

## ② NEW FEATURES  *(after hardening)*

### Capable agents  *(make agents genuinely do things, not just chat)*
- [ ] **Custom action tools** — let the agent *write* to apps (POST/create), not just read.
- [ ] **MCP client** — add a Model Context Protocol server → agent gains its tools
      (ecosystem-standard; Turnstone/Claude/Cursor use it).
- [ ] **Multi-step planning loop** — plan → act → observe → verify, not one-shot answers.
- [ ] **Self-verification** — agent checks its own result before claiming "done".
- [ ] **Reliable tool-calling** — structured outputs; fix small-model flakiness.
- [ ] **Per-agent working memory** — each agent remembers what it has done (partly there).
- [ ] **Accountability-loop routine** — reminder → wait for check-in → re-nudge ×2 →
      mark "absent" (from the to-do-list request).
- [ ] **Streaming responses** + inline tool-call trace.
- [ ] **Learn the user's writing style** — drafts sound like them (Turnstone does this).
- [ ] **On-demand Gmail fetch** — lazy fetch beyond the synced window (like Drive).

### Brain as a service  *(let ANY external agent use the brain — big differentiator)*
- [ ] **MCP server** ⭐ — expose the brain as MCP tools (`search_brain`, `remember`,
      `get_entity`, `list_sources`) so Claude Desktop / Cursor / ChatGPT / custom
      agents can query the user's second brain. Positioning: *the private memory
      layer for every AI you use.*
- [ ] **Token-authed local REST** — documented `/api/brain/query` for scripts /
      n8n / Zapier-style automations.
- [ ] **Security model** — localhost-only bind · per-agent API keys · read vs
      read+write scopes · audit log · one-click revoke. (Prereq for both above.)

### More actions
- [ ] Reply / forward email · update/complete task · reschedule event · Slack message.

### More connectors  *(single-token or local — cheap on our pattern)*
- [ ] Slack · Todoist · Trello · Readwise/Raindrop (single-token → reuse secret field).
- [ ] Browser history · Obsidian/markdown vaults · Bear (zero-auth local).
- [ ] Microsoft / Outlook / OneDrive (OAuth — heavier).
- [ ] Granola (meeting notes — Turnstone parity).

### Brain / scale
- [ ] **Tier-2 scaling** — sqlite-vec (ANN) + FTS5 + incremental indexing (>30–50k memories).
- [ ] Smarter chunking + re-ranking.

### Distribution / packaging
- [ ] PyInstaller → **signed, notarized DMG** (self-contained, runs on any Mac).
- [ ] In-app **auto-update** ("update available").
- [ ] Windows / Linux builds.
- [ ] **Google app verification (CASA)** — needed to offer public Gmail scopes
      without the test-user list.

### Onboarding
- [ ] First-run **"Connect your data"** screen (Google vs local vs custom).
- [ ] Guided setup + sample queries so the brain isn't empty on day one.

---

## ③ UI / UX REDESIGN  *(you — after features are solid)*
- [ ] Full visual redesign (your direction).
- [ ] Design system, responsive layout, dark/light, animations.
- [ ] *(Everything above is engine-level, so a redesign won't fight the backend.)*

---

## ④ LANDING PAGE  *(last)*
- [ ] Marketing site (what it is, privacy story, "connect any app", BYO model).
- [ ] Docs site (install, connectors, model setup).
- [ ] Demo video / GIFs.
- [ ] Positioning vs Turnstone + the Indian-SMB wedge.

---

## Known constraints (won't "fix" — inherent trade-offs)
- **claude-code** backend: latency + uses your Claude session limits. Fallback: ollama.
- **Cloud models** receive injected context at query time; only a **local** model
  keeps everything fully on-device. This is fundamental, not a bug.
- **Custom apps run no code** (declarative only) — deliberate: no arbitrary-code
  execution / RCE risk. The agent composes safe primitives, it doesn't write code.
