# Lodestone — Decision Log (ADRs)

> Every important architectural/product decision, with the reasoning. Newest at
> the bottom of each section. This is the "why we did it this way" record.
> Companions: [`context.md`](../context.md) (direction), [`PROJECT.md`](PROJECT.md)
> (how it works), [`CONCEPTS.md`](CONCEPTS.md) (the ideas from scratch).

---

## Product / strategy

### D1 — Build a faithful, open Turnstone (myturnstone.ai, YC W26)
Clone the real product: a local-first AI **workspace** where named agents share a
**second brain** built from your apps and act using **any model you bring**.
NOT the passive MCP memory-server we first (wrongly) built.
**Why:** it's what Turnstone actually is; agents that *do work* are the point.

### D2 — North Star: private "knows-your-work" assistant, depth-first (NOT Jarvis)
Match Turnstone's shape; grow "does things" abilities over time. Do not chase a
broad voice/life-OS ("Jarvis").
**Why:** Jarvis competes with Apple/Google/OpenAI and is never "finishable" — the
opposite of the goal (a polished, finished product). Depth is finishable and
defensible (big clouds won't do local/private well).

### D3 — Polished, finished quality bar (not demo-grade)
Hold a high bar on every change; fix rough edges properly.
**Why:** the portfolio should contain finished products, not half-built demos.

### D4 — Every fix must be SYSTEMIC (automatic for all users)
No manual data surgery as "the fix" — dedup, migrations, syncs, cleanups must be
code that self-heals for every user, on startup / on sync / on schedule.
**Why:** it's a product for many users; they can't run scripts or CLI. If a bug
needs a manual fix, that fix belongs in the system.

### D5 — Likely wedge: Indian small businesses (later specialization)
Same engine, pointed at a market Turnstone won't serve. Not the current focus.

---

## Architecture

### A1 — Python + FastAPI + web UI (web-first, desktop-later)
**Why:** fastest to a working demo; a Tauri/Electron shell can wrap the same
engine later with zero rewrite. Web now, app later — not either/or.

### A2 — Agent-first: agents are the core primitive
Brain, models, tools, connectors all exist to serve agents.
**Why:** matches what the product is — you talk to agents that act.

### A3 — Four preset agents sharing one brain (Inbox, Launch, Research, Personal)
Turnstone's exact set. Each domain-scoped; all share one brain.
**Why:** faithful parity; shared brain = "what one learns, all know."

### A4 — Bring-your-own-model via a provider abstraction
One interface; backends: claude-code, anthropic, openai, openrouter, ollama,
subscription-gateway, mock. Switchable in the UI, per message.
**Why:** BYO model is Turnstone's core promise; abstraction means agent code
never changes when you swap models. `mock` keeps everything testable offline.

### A5 — Default to a free LOCAL model (Ollama), later added claude-code
**Why:** most on-brand for local-first/private; zero keys/cost. `claude-code`
(runs the user's terminal Claude via `claude -p`) added for much smarter answers
using the user's own Claude — at the cost of latency + usage.

### A6 — Local SQLite for everything; vectors as BLOBs searched in NumPy
No external DB. `~/Library/Lodestone/*.db`.
**Why:** local-first, zero-config, portable, ships inside a desktop app. Fine to
tens of thousands of memories. Deferred: sqlite-vec + FTS5 (Tier 2) at scale.

### A7 — Knowledge-graph brain (GraphRAG), built from CURATED prose only
Vector memories + an entity/relation graph; graph is built from notes/manual/
agent/notion + prose files — NOT bulk email or Drive.
**Why:** vectors give coverage, the graph gives precise structured recall; but
email/Drive HTML pollutes the graph (DOCTYPE/Arial/Subject), so they stay
searchable memories without polluting entities.

### A8 — Semantic embeddings: upgraded MiniLM → BGE (bge-small-en-v1.5)
With query-instruction prefixes (embed_query).
**Why:** MiniLM ranked "Security alert" above "You're Selected for HackWithUP";
a real Gmail lookup failed. BGE fixed it (target went from not-in-top-15 → #3).

### A9 — Context grounding: inject what the model can't know, every turn
Auto-recall (brain), current date/time, current tasks, and (for domain agents) a
source preference are injected before the model runs.
**Why:** LLMs are stateless and have no clock; small models won't reliably call
tools. Injecting facts deterministically = "already knows you" on any backend.

### A10 — Date-aware retrieval
Parse a date/range from the query ("emails on July 14", "todays mails", "last
week") and filter memories by their real `event_date` (Gmail/Calendar/Drive
store it). Compact overview rendering so a whole day's items fit.
**Why:** semantic search can't retrieve by date — a date is a filter, not a
meaning. Possessive/plural forms (todays/yesterdays) are handled.

### A11 — Source overviews ("what's in my drive/inbox/calendar")
Detect listing intent + a source; inject a DISTINCT file/email/event listing
(grouped by uri so multi-chunk PDFs count once).
**Why:** "what's in my drive" is a listing request semantic search can't answer
(docs don't contain the word "drive").

### A12 — On-demand Drive fetch (lazy loading)  ← key recent decision
Keep a **bounded** brain (capped sync). When the user asks for a document NOT in
the brain, do a **live targeted Drive search** (name + full-text, incl.
Shared-with-me) and ingest just that file, then answer. Done in the RECALL layer
(not a model tool) so it works on any backend, incl. claude-code.
**Why:** "Shared with me" has hundreds of unrelated files — syncing all is bloaty
AND unreliable for finding one. Lazy loading = bounded index + long-tail on
demand. The user proposed this; it's the right design.

### A13 — Continuous background sync + self-heal
A scheduler re-syncs ready connectors on a timer (default 30m) and on startup;
re-syncs are cheap (store skips content it already has). It runs `dedupe()` on
startup and after every sweep.
**Why:** Turnstone "continuously updates"; and per D4, dedup/heal must be
automatic — no user runs a dedup script.

---

## Connectors

### C1 — Read-only, lazy-imported SDKs, graceful when unconfigured
All connectors read-only; each shows readiness + a setup guide in the UI.

### C2 — Files connector guardrails (cap + junk filters)
Refuse >LODESTONE_MAX_FILES (default 2000); skip build/vendor/lock/minified/
node_modules. **Why:** a folder sync once bloated the brain to 82k memories/433MB
(unrelated project code). Guardrails + a configurable cap prevent recurrence.

### C3 — Google connectors share one OAuth (Gmail/Calendar/Drive)
One Desktop OAuth client, read-only scopes, token cached. `client_secret.json`
lives outside the repo and is gitignored. **Why:** one consent, three sources;
never commit secrets.

### C4 — Gmail: all mail (paginated) + HTML stripping + real dates
Default query is all mail up to LODESTONE_GMAIL_MAX (1500), bodies converted to
clean text (drop CSS/tags), each email tagged with its date.
**Why:** 30-day/50-msg default was too small; CSS leaked into summaries; dates
enable date queries.

### C5 — Drive: Office formats + Shared-with-me/Shared-Drives + file dates + skip
Parses .docx/.pptx + Google Slides; lists Shared-with-me and Shared Drives;
stores modifiedTime as date; skips re-downloading unchanged files (file_id).
**Why:** the resume (.docx) and shared course notes were invisible; re-downloads
made syncs slow.

### C6 — Added Google Calendar + iMessage connectors
Calendar reuses Google auth (fixed a Brain.ingest metadata bug that crashed it);
iMessage reads the local macOS chat.db (Full Disk Access, no cloud).

---

## Notable bugs fixed (root-caused in code, not patched by hand)

- **claude-code blank error** — fake User:/Assistant: transcript tripped its
  stop-sequence; now uses --append-system-prompt + parses is_error.
- **"claude.ai connector isn't authorized" hallucination** — claude-code (real
  Claude) confused its own connectors with Lodestone; prompt now forbids it and
  states data is already in the brain.
- **Recall missed real emails** — MiniLM weakness → BGE (A8) + source preference.
- **Email/Drive HTML in the graph** — graph now curated-prose only (A7).
- **Calendar crash** — Brain.ingest didn't accept `metadata`.
- **1,451 duplicate emails** — earlier manual in-place cleanup + re-sync; fixed by
  systemic auto-`dedupe()` on startup + after sync (D4).
- **Resume/shared notes invisible** — .docx support + Shared-with-me + on-demand
  fetch (C5, A12).
- **parse_when crashed on invalid times** — "9:99"/"3:70" raised an uncaught
  ValueError that could kill the reminder/action flow; now range-validated → None.
- **Gmail base64 crash aborted the whole sync** — Gmail returns unpadded base64url;
  `_decode` raised "Incorrect padding", and since the message loop shared one try,
  ONE such email lost all remaining mail. Now re-pads + isolates each message (H4).
- **Google auth stuck on expired/corrupt token** — a revoked refresh token (7-day
  Testing-mode expiry) or corrupt token file failed every future sync forever with
  the stale token never cleared. Now self-heals: drop + re-consent (H5).
- **Custom-API field-less records collapsed to one "None"** — str(None) is truthy so
  the `or` fallback never fired; field-less rows deduped to a single record (H8).
- **"database is locked" under scheduler+API concurrency** — no busy_timeout; added
  5s busy_timeout (+ WAL) on every DB (H6).
- **claude-code "not found" as a GUI app** — Finder gives a stripped PATH; now searches
  Homebrew/npm-global/Claude-local and passes an augmented PATH to the subprocess (H1).

---

## Production hardening & trust (H-series — the "make it a finished product" pass)

### H1 — GUI-safe binary + platform-aware connectors
Finder-launched apps get a minimal PATH; `claude` is found across Homebrew (Apple
Silicon + Intel), npm-global and `~/.claude/local`. Connectors declare `platforms`;
Apple Mail/Calendar/iMessage are darwin-only and hidden off macOS instead of shown broken.

### H2 — Crash-isolation everywhere (one bad item never aborts a sync)
Every list-syncing connector (Gmail, Calendar, Notion, Linear, GitHub, custom API)
isolates each record: a malformed item is counted as skipped and the sync continues.

### H3 — Providers fail with clear messages, never raw tracebacks
OpenAI-compatible `chat()` maps unreachable host / 401·403 / 429 / 5xx / timeout /
malformed response to short, actionable text. An engaging reply indicator (pulsing
dot + cycling status + countdown + progress bar) replaces the static "thinking…".

### H4 — Gmail base64url decode tolerates missing padding *(see bugs)*
### H5 — Self-healing Google auth (corrupt/expired token → re-consent) *(see bugs)*
### H6 — SQLite busy_timeout=5000 + WAL on all DBs *(see bugs)*

### H7 — Input validation & safety at the API edge
Empty/whitespace chat rejected (422, no wasted model call); chat/ingest payloads
size-capped; custom-app URLs must be http(s) (urllib would otherwise read file://);
email recipients validated against a real address pattern before send.

### H8 — Custom API connector (connect any REST app, no code)
Declarative: base URL + endpoint + auth (bearer/header/query) + dot-path field
mapping; fetched and ingested like a built-in. No arbitrary code (no RCE). Field-less
records stay distinct (see bugs).

### H9 — In-app secret fields + macOS Keychain (encrypted at rest)
Token connectors (Notion/Linear/GitHub/custom) declare a `secret_field` → the UI
renders an in-app input, no `.env`. Secrets are stored in the **macOS Keychain**
(encrypted at rest by the OS); env var → Keychain → legacy file resolution, with
plaintext-file secrets migrated out on next save.

### H10 — "What leaves my device" transparency badge
Each model backend is classified local (Ollama/mock — stays on-device) or cloud
(claude-code/anthropic/openai/openrouter/subscription — context sent off-device),
shown as a 🔒/☁️ badge with a tooltip naming the destination. Serves the North Star (D2).

### H11 — Brain export / import (you own your data)
Portable JSON backup of every memory (no vectors); import re-embeds under the current
embedder and rebuilds the graph, so a backup survives an embedder change or a new Mac.
Dedup makes re-import idempotent.

### H12 — Bundled Google Desktop OAuth client is committed
Installed-app client secrets are non-confidential (PKCE + localhost redirect), so the
Desktop client ships in-repo → testers get one-click sign-in on a fresh clone. Regenerate
if secret-scanning ever revokes it.

### H13 — First-run onboarding flow
A "connect your data" screen with four real choices (Sign in with Google · local Mac
sources · connect an app · tell it a fact), shown on a fresh/empty brain and reopenable
via "? Getting started".

### H14 — Per-connector sync feedback + stale-at-a-glance
Live "syncing…" state per row; overdue connectors show an amber "stale" dot.

### H15 — Test suite expanded 6 → 59; scheduler/routines log failures
Edge-case regression tests (parse_when, actions, custom API, Gmail decode, auth
self-heal, migrations, reminders, export/import, API validation, MCP). Background
loops `log.exception` instead of silent `pass`.

### H16 — MCP brain-as-a-service (the private memory layer for any AI)
Lodestone exposes its brain to any MCP client (Claude Desktop/Code, Cursor) over
stdio via `lodestone/mcp_server/server.py` — 8 tools: `search_brain`, `about`
(knowledge-graph lookup), `remember`, `web_search`, `brain_stats`, `list_tasks`,
`add_task`, `complete_task`. Correct for **mcp 2.x** (FastMCP→MCPServer). Local-only
(stdio, spawned by the client — no network/auth needed). `lodestone mcp-install`
prints the one-line registration. This makes the brain usable by *every* AI, not
just Lodestone's own agents — the biggest differentiator (D2).
- `about()` guard: BGE gives unrelated short phrases a high baseline cosine, so it
  requires the entity name to share a word with the query (or score ≥0.8), else a
  query returns near-random entities.

### Observation (to investigate) — LLM-extractor graph noise
When the extractor uses **claude-code**, it inherits the user's Claude memory /
project context, so extracting an unrelated sentence can add personal entities that
aren't in the text (e.g. "Dev", "macOS Keychain"). Only affects the LLM-extractor
path (manual ingest / `remember`); connector bulk syncs use the clean heuristic
(`fast=True`). Candidate fix: constrain the extractor prompt to the given text only,
or prefer the heuristic for single short ingests.

---

## Desktop sign-in & window behaviour (W-series)

> Full record, with measurements and the wrong turns:
> [`DESKTOP-SIGNIN.md`](DESKTOP-SIGNIN.md).

### W1 — The floating card is raised by the page, never by the API
`window.pywebview.api.open_signin_hud(...)` from the frontend; the backend never
creates a window.
**Why:** under `lodestone app --dev` the backend is a separate uvicorn process
with no handle on the webview, so a backend-initiated window silently did
nothing. The frontend always runs inside the webview.

### W2 — `NSFloatingWindowLevel`, not `NSStatusWindowLevel`
pywebview's `on_top` gives status level (25). We set floating (3).
**Why:** status level also covers the menu bar and system UI, which a sign-in
card has no business claiming. Level was never the bug — see W3 — so the higher
level bought nothing and cost correctness.

### W3 — `CanJoinAllSpaces | FullScreenAuxiliary`, and NOT `Stationary`
**Why:** the card "going behind other apps" was never z-order. A window with the
default collection behaviour belongs to the Space it was created on, so switching
Spaces left it behind — measured, `isOnActiveSpace` went `False`. `Stationary`
pins a window to screen coordinates during Space transitions (for wallpaper-like
overlays) and is redundant once a window joins every Space; tested, changed
nothing. Applying every flag that sounds relevant is how a floating panel starts
behaving like a screen-saver overlay.

### W4 — Accept that the card cannot cover another app's full-screen Space
**Why:** measured across levels 3/25/101, with and without `Stationary`, and with
an accessory activation policy — none reach it. Apps that manage it are
`LSUIElement` accessory apps using a non-activating `NSPanel`; pywebview creates
a plain `NSWindow`, and making Lodestone dockless is not worth this. The in-app
row in the Models panel is the fallback, which is why it stays on screen even
when the floating card is up.

### W5 — `orderFrontRegardless()` instead of the backend's `show()`
**Why:** pywebview's `show()` is `makeKeyAndOrderFront_` +
`activateIgnoringOtherApps_`, which pulls keyboard focus out of the browser the
user is signing in to — on every card update. A click on the card still brings
the app forward normally.

### W6 — The window sizes itself to the card
`_Bridge.fit` → `_resize_now`, driven by a `ResizeObserver` and re-run on
`document.fonts.ready`, anchored at the **top** edge.
**Why:** the copy differs per provider and per state, so a fixed height either
leaves a hole under the text or clips it. Cocoa's origin is the bottom-left, so
resizing naively walks the card up the screen. `overflow: hidden` on `html, body`
is load-bearing: a window a pixel short grows a scrollbar, which rewraps the text
and makes the card taller, so the window chases a height that keeps moving.

### W7 — The webview's backdrop is cleared, not just the window
**Why:** a transparent window is not enough. WKWebView fills its bounds with
`underPageBackgroundColor` (opaque white, measured at alpha 1.0), which showed as
a white block below the card. pywebview's transparency support predates that
property and only clears the older `drawsBackground`.

### W8 — Anything we spawn, we clean up — across runs
`models/login_processes.py` records every vendor-CLI login to disk; `run_app`
reaps on launch and on quit; only recorded PIDs are signalled, and only after
re-checking the command line.
**Why:** a CLI `login` waits for a browser callback that may never come, nothing
reaped them, and the handle lived in module state so each launch forgot the last
one's. **158 were found alive on one machine**, each holding the vendor's OAuth
callback port until sign-in stopped working. A reused PID killed is worse than
the leak, hence the command-line re-check.

### W9 — The webview origin is user state, so the port is fixed
`_reserve_port` binds the saved port the way uvicorn does (**`SO_REUSEADDR`**) and
hands that socket to the server.
**Why:** `localStorage` is keyed to the origin. The old probe bound without
`SO_REUSEADDR`, so a port left in `TIME_WAIT` by the server that had just exited
read as taken; the app moved to a random port and the onboarding flag, chosen
model and lead agent all silently vanished. Symptom: **every other launch opened
empty.**

### W10 — Tests may never start a real sign-in
`conftest.py` swaps the argv of any `login` spawn for a command that exits at once.
**Why:** `flow.start()` and `POST /signin` reach `claude auth login` for real, and
**every pytest run left one alive** — the dominant source of W8's 158. The flows
still run their own code; only the vendor binary is kept out. Third test-hygiene
incident here, after tests writing to the real Keychain and binding port 1455.

---

## Deferred (tracked, do later)

- **Tier 2 scaling**: sqlite-vec (ANN) + FTS5 + incremental indexing, for when the
  brain passes ~30–50k memories.
- **Auto-migration versioning**: stamp a data version; on startup, auto re-embed /
  rebuild-graph when the extractor/embedder changes (so these stop being manual).
- **UI-based OAuth**: authorize connectors from the UI, no CLI.
- **Action-taking**: agents that *do* ("draft a reply") with confirmation.
- **On-demand fetch for Gmail** (like Drive): "find the email where X sent Y".
- **Tauri desktop shell**; **custom user-defined agents**.
