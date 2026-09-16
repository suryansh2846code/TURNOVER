# Chitragupta — Roadmap / Backlog

> What's left to build, recorded so we can revisit after each item ships.
> Reviewed 13 Sep 2026. See [`JOURNEY.md`](JOURNEY.md) for how we got here,
> [`DECISIONS.md`](DECISIONS.md) for the "why", [`AUDIT.md`](AUDIT.md) for
> defects (this file is for work that is wanted; that one is for work that is
> owed).

## Shipped since this list was written
- [x] **Action-taking** — propose/confirm via the `<action>` tag, executed in
      code. Unattended paths are permission-gated; see
      [`AGENTS.md`](AGENTS.md).
- [x] **Custom agents** — name, focus, prompt and tool subset, stored as data.
- [x] **Auto-migration versioning** — `core/db.py::_migrate` plus the startup
      self-heal in `scheduler.py`.
- [x] **The agent loop** — depth, parallel tools, conversation compaction,
      agent-to-agent delegation, planning, streaming on every backend, and a
      capability scorecard. [`AGENTS.md`](AGENTS.md).
- [x] **MCP client** — a remote server's *read* tools are callable inside a
      turn, discovered per install and attributed to the connector the user
      named. Writes keep the propose-then-confirm path; the reason they must is
      in `agents/permissions.py`. Built 2026-09-13 across four sessions
      (`connectors/mcp_tools.py`, `agents/mcp_tools.py`, the Tools panel, and an
      injection suite written before the feature landed).

## Next up (priority order)
1. [ ] **Full Disk Access handling** — iMessage and Apple Mail need it, no
       prompt can request it, and without an explanation the app simply looks
       broken on someone else's Mac. The largest gap between "the `.dmg` builds"
       and "the `.dmg` works for a stranger". See [`DISTRIBUTION.md`](DISTRIBUTION.md).

       **Shipped 2026-09-15** (`bcfd70d`). `connectors/permissions.py` is the one
       place that sentence exists and the one place that knows which System
       Settings pane clears it; `desktop.py::_AppBridge.open_privacy_settings`
       opens it, and the connector row renders a button from the `fix` field
       rather than telling anyone to find their terminal.
2. [x] **UI for effort, permissions and approvals** — **shipped.** Effort is a
       control in the Model screen reading and writing `GET/POST
       /api/agents/effort` (`models.js::loadAgentDefaults`). The allow-list is
       *Acting without asking* in the same screen, plus an **Always allow
       &lt;address&gt;** button on the approval card itself — the grant is offered
       where the user learns they want one, and reviewable where it can be taken
       back. The card offers it only when `blocked` is non-empty, so it is never a
       control that cannot work.
3. [x] **UI-based OAuth** — **shipped.** `POST /api/google/reconnect` runs consent
       on a background thread and `GET /api/google/status` reports the result;
       `brain.js::connectGoogle` polls it behind one *Sign in with Google* button.
       No terminal anywhere in the path.

> **All three were stale when read on 2026-09-16** — two were already built and
> this list still called for them, which sent a session to rebuild work that
> existed. Tick an item in the commit that ships it; a roadmap nobody trusts is
> worse than no roadmap.

## Agent gaps worth naming
Detail in [`AGENTS.md`](AGENTS.md) → *What is still missing*.
- [ ] **A turn-wide token budget.** Depth and per-agent budgets bound delegation,
      but three agents at High is still a lot of model calls on the user's own
      plan.
- [ ] **Answer-quality evaluation.** The scorecard measures the harness; whether
      an answer is *good* needs a real model and a person.
- [ ] **The plan is advisory** — nothing checks at the end whether the steps the
      agent wrote for itself were actually done.
- [ ] **`tools.py` at 65% coverage**, the lowest in the agent layer and the part
      that touches the real world.

## Deferred — needs a product decision

### Recall scaling
**Status:** measured, deliberately not built. See [`SCALING.md`](SCALING.md).

Recall is linear in memory count (~0.05 ms each) and runs on every agent turn.
A real install sits at 3.3k memories / ~120 ms, which is fine; 10k is 430 ms
and 50k is 2.5 s. The bottleneck is **not** vector search — the matmul is 0.1%
of the time — it is the eight-factor Python scoring loop that runs over every
row (95%). A top-K pre-filter before that loop measured **25–33× faster** (50k:
2.3 s → 70 ms) as a contained change to one function.

Not needed yet because the app is bounded by default (Gmail 600/90d, Drive 500,
Files 2000). **The real risk is the uncapped connectors** — iMessage has no
limit at all, and years of history would land a user at 100k+ from one
checkbox. Capping those is cheaper than optimising recall, and should come
first.

**Reopen if:** a real brain passes ~10k memories, an uncapped connector ships,
or recall stops being once-per-turn.


### Grok subscription support (xAI) — **shipped**
Built 2026-09-12 via xAI's official Grok Build CLI (`models/grok_cli.py`).

`api.x.ai` is the *developer* API, billed from console.x.ai credits, and a
SuperGrok subscription grants none — verified against a real account, where even
the free metadata call fails:

```
GET  /v1/models            403  personal-team-blocked:spending-limit
POST /v1/chat/completions  402  personal-team-blocked:spending-limit
```

An earlier version of this entry wrongly claimed there is no official Grok CLI
and that subscription support would need grok.com's private backend. xAI ships
**Grok Build** (`curl -fsSL https://x.ai/cli/install.sh | bash`, or
`npm i -g @xai-official/grok`), and the sanctioned headless path is:

```
grok -p "<prompt>" --output-format json -m <model>   # single-turn, prints and exits
grok login --oauth                                   # browser sign-in at accounts.x.ai
grok models                                          # what this account may run
```

That is the same shape as the Claude Code and Cursor backends, and what the
`grok-cli:access` scope on our OAuth token is for.

**Bundling shipped** — `models/cli_manager.py` downloads and pins the CLI, so
users install nothing by hand. Artifacts are fetched directly; the vendor's
install script is read as a manifest, never executed.

**Note:** `models/xai_auth.py` still authenticates with client id `b1a00492-…`
and `referrer=opencode` — **not ours**. That OAuth flow is unreachable now
(GrokFlow replaced it); delete it or replace the client id.

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
- **The floating sign-in card cannot cover another app's full-screen Space.**
  Measured across levels 3/25/101, with and without `Stationary`, and with an
  accessory activation policy — none reach it. Apps that manage this (Alfred,
  Raycast) are `LSUIElement` accessory apps using a non-activating `NSPanel`;
  pywebview creates a plain `NSWindow`, and making Chitragupta dockless is not a
  trade worth it. The in-app row in the Models panel is the fallback, which is
  why it stays on screen even when the card is up. See
  [`DESKTOP-SIGNIN.md`](DESKTOP-SIGNIN.md).
- **Multi-display placement is correct by construction but unverified.** The card
  is positioned against `NSScreen.visibleFrame` on the screen under the pointer;
  only one display was available to test on.
- **claude-code** backend: latency (spawns a Claude session per message) + your
  Claude usage/session limits. Fallback: switch to `ollama` (free, local).
- Cloud models send the injected context to the provider at query time; only a
  local model keeps everything on-device.

## Done (recent, for reference)
Agent-first workspace · BYO model (claude-code/ollama/…) · knowledge-graph brain ·
BGE semantic recall · Gmail (all-mail, HTML-stripped, dated) · Calendar · Drive
(.docx/.pptx + Shared-with-me) · date-aware retrieval · source overviews ·
continuous background sync · self-healing dedup · **on-demand Drive fetch (lazy
loading)** · full docs (PROJECT/CONCEPTS/DECISIONS/JOURNEY) · **per-user model
entitlements (no hardcoded catalogs)** · **bundled vendor CLIs** · **independent
account/API-key credentials** · **one sign-in protocol (`auth_flows`)** ·
**translated provider errors** · **floating sign-in card that follows the user
across Spaces** · **vendor-login process cleanup** · **model-layer freeze suites
(42 invariants)**.
