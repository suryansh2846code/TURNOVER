# Lodestone — Roadmap / Backlog

> What's left to build, recorded so we can revisit after each item ships.
> Status as of 30 Aug 2026. See [`JOURNEY.md`](JOURNEY.md) for how we got here,
> [`DECISIONS.md`](DECISIONS.md) for the "why".

## In progress
- [ ] **Auto-migration versioning** — stamp a version on embeddings / graph /
      schema; on startup auto re-embed / rebuild-graph when the code version
      changes, so no user (or dev) ever runs a manual migration. *(building now)*

## Next up (priority order)
1. [ ] **Action-taking** — the biggest Turnstone gap. Agents currently *draft*
       but can't *do*: send an email, create a calendar event, reply. Build with
       an explicit **confirm-before-acting** step. Needs write-scoped connectors.
2. [ ] **UI-based OAuth** — connect Gmail/Drive/Calendar from the workspace, no
       terminal/CLI. Required for non-developer users.
3. [ ] **Custom agents** — let users create their own agent (name, focus, tools),
       not just the 4 presets. Turnstone feature.

## Deferred — needs a product decision

### Grok subscription support (xAI)
**Status:** deliberately not built. xAI is API-key-only in the app today.

**Why.** xAI sells two separately-billed products that share one login:

| | SuperGrok subscription | xAI developer API |
|---|---|---|
| Bought at | grok.com | console.x.ai |
| Endpoint | `grok.com/rest/…` (private) | `api.x.ai/v1/…` (documented) |
| Billing | monthly subscription | per-token credit balance |

A subscription grants **no** credits on `api.x.ai`. Signing in with Grok
therefore authenticates successfully and then fails every request — verified
against a real account on 2026-09-12, including the free metadata call:

```
GET  /v1/models            403  personal-team-blocked:spending-limit
POST /v1/chat/completions  402  personal-team-blocked:spending-limit
```

Team-id headers make no difference; the OAuth token carries `api:access` scope,
so this is billing refusing, not auth failing. Competing apps that do run Grok
on a subscription are talking to grok.com's consumer backend instead.

**What shipping it would require, and cost:**
- Capturing grok.com's request shape — it is undocumented, so it cannot be
  inferred, only observed from a client that already speaks it.
- Presenting as a first-party client. Note `models/xai_auth.py` already uses
  client id `b1a00492-…` with `referrer=opencode` — **not ours**. Any real
  implementation should start by replacing that with a Lodestone-owned client.
- Accepting that a private consumer API can change without notice and break
  every user at once, and that this sits in a grey area of xAI's terms.

**Until then** the app is honest about it: `XAIProvider._oauth_only` reports
not-ready with an explanation instead of authenticating, looking connected, and
failing on the first message. The OAuth plumbing in `models/xai_auth.py` is left
in place but unreachable — `capabilities.py` marks xAI `api_key_only`, so no
sign-in button is offered.

**Reopen if:** xAI publishes a subscription-backed API or an official CLI (there
is none as of Sept 2026), or the team decides the private-endpoint trade-off is
worth it.

## Should do
4. [ ] **Test Notion + iMessage connectors with real data** — built, never
       verified end-to-end (Notion needs a token; iMessage needs Full Disk Access).
5. [ ] **On-demand fetch for Gmail** — like Drive: "find the email where X sent
       me Y" lazily fetches beyond the synced window.
6. [ ] **Learn the user's writing style** — capture past emails/messages as style
       exemplars so drafts sound like the user (Turnstone does this).
7. [ ] **Expand automated tests** — only ~6 smoke tests today; add coverage for
       recall, date parsing, connectors, on-demand fetch, dedupe, migrations.

## Later / deferred
8. [ ] **Tier-2 scaling** — sqlite-vec (ANN) + FTS5 + incremental indexing, for
       when the brain passes ~30–50k memories (currently ~3k, fine).
9. [ ] **Tauri desktop app** — wrap the same engine in a native Mac shell
       (menubar, autostart); web-first today.
10. [ ] **Small-model reliability** — qwen/llama tool-calling is occasionally
        flaky; mitigated (grounding, low temp) not eliminated.
11. [ ] **More connectors** — Slack, Linear, browser history, Granola (Turnstone's
        full set).

## Known constraints (not bugs, won't "fix")
- **claude-code** backend: latency (spawns a Claude session per message) + your
  Claude usage/session limits. Fallback: switch to `ollama` (free, local).
- Cloud models send the injected context to the provider at query time; only a
  local model keeps everything on-device.

## Done (recent, for reference)
Agent-first workspace · BYO model (claude-code/ollama/…) · knowledge-graph brain ·
BGE semantic recall · Gmail (all-mail, HTML-stripped, dated) · Calendar · Drive
(.docx/.pptx + Shared-with-me) · date-aware retrieval · source overviews ·
continuous background sync · self-healing dedup · **on-demand Drive fetch (lazy
loading)** · full docs (PROJECT/CONCEPTS/DECISIONS/JOURNEY).
