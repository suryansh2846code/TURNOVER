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
