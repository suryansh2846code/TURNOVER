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
