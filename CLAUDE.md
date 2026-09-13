# Lodestone — working notes for Claude

Local-first AI **agent workspace**: a team of agents share one on-device "brain"
(memories + a knowledge graph) built from the user's connected sources. Bring your
own model. Everything runs and stays on the user's machine.

## Read this before you edit anything

This file is the operating manual for the repo: the product doctrine, the
model-availability rules, the agent-loop invariants, the layout and the
conventions. Almost every rule below is load-bearing for a bug that already
shipped, and the paragraph explaining *why* is usually worth more than the rule —
so when something here looks like over-explanation, it is the evidence.

Each code directory carries a short `CLAUDE.md` of its own (`lodestone/web/`,
`lodestone/models/`, `tests/`, …). Those **narrow** this file for that directory
and never contradict it; if they disagree, this file wins and the directory note
is wrong. No rule is written in two places — a duplicated rule drifts, and the
copy that drifts is always the one you read.

**One session works this repo at a time.** For one day it was built by eight in
parallel, one per subsystem, with an ownership map and a handoff log; that is
retired, and what it cost is recorded in
[`docs/DECISIONS.md`](docs/DECISIONS.md) → F1. One lesson survived, because it
was never about parallelism: **when a change spans two layers, write down what
the boundary names and land both sides together, with a test that fails if only
one of them ships.** Two halves that each pass their own tests can still be
wrong about each other, and that is not a hypothetical here — it shipped.

## This is a product, not a developer tool
Lodestone ships to people who did not build it. **Every decision is a product
decision** — when there is a trade-off between "correct for an engineer" and
"works for the person who installed this", choose the second and make it
correct underneath.

What that means concretely, and what it has already changed:

- **Never ask the user to open a terminal.** The vendor CLIs that back
  subscription sign-in (Cursor, Grok, and Claude Code) are downloaded, pinned
  and managed by us — `models/cli_manager.py`, into
  `~/Library/Lodestone/agent-binaries/` with symlinks in `bin/`. One button,
  with progress. A copyable command is the fallback, never the plan.
- **Never show a control that cannot work.** A sign-in button that opens a page
  we learn nothing from, a model that 404s when selected, a "Connected" badge
  with no credential — each of these shipped here and each read as "the app is
  broken". If a path cannot succeed, say why, in the place the user is looking.
- **Never surface an internal.** No raw provider JSON, no stack traces, no
  internal ids in user-facing text. Errors say what happened and what to do
  (`models/errors.py`).
- **A floating card is a Spaces problem, not a z-order problem.** *(Full record,
  with the measurements and the wrong turns:
  [`docs/DESKTOP-SIGNIN.md`](docs/DESKTOP-SIGNIN.md).)* The sign-in
  card kept vanishing when the user switched to the browser. It was never
  *behind* anything — pywebview's `on_top` already gave it `NSStatusWindowLevel`
  (25), above every normal window. With the default collection behaviour a
  window belongs to **the Space it was created on**, so switching Spaces left it
  behind. `hud._apply_float_behaviour` sets
  `CanJoinAllSpaces | FullScreenAuxiliary`, drops the level to
  **`NSFloatingWindowLevel`** (above every app's normal windows, below the menu
  bar — status level claimed system UI it has no business covering), and sets
  `hidesOnDeactivate = False`. *Not* `Stationary`: that pins a window to screen
  coordinates during Space transitions, for wallpaper-like overlays, and is
  redundant once a window joins every Space.
  **Known macOS limit:** none of this reaches *another app's full-screen Space*.
  Measured directly — levels 3, 25 and 101, with and without `Stationary`, and
  with an accessory activation policy, all fail to appear over a full-screen
  browser. Apps that manage it (Alfred, Raycast) are `LSUIElement` accessory
  apps using a non-activating `NSPanel`; pywebview creates a plain `NSWindow`,
  and making Lodestone dockless is not a trade worth this. The in-app row in the
  Models panel is the fallback, which is why it stays on screen either way.
- **Showing the card must not activate the app.** The backend's `show()` is
  `makeKeyAndOrderFront_` + `activateIgnoringOtherApps_`, which yanks keyboard
  focus out of the browser the user is signing in to — every time the card
  updates. Use `orderFrontRegardless()` and let a click bring the app forward
  normally. Every Cocoa window mutation goes through `AppHelper.callAfter`:
  calling these setters from the js_api worker thread hangs the process.
- **Position against `NSScreen.visibleFrame`, on the screen under the pointer.**
  `webview.screens[0]` is the primary display's *full* frame — wrong monitor on a
  multi-display desk, and it ignores the menu bar and Dock. Points, not pixels,
  so Retina and mixed-scale arrangements need no special case.
- **Follow the user out of the app.** A browser sign-in leaves Lodestone, so the
  status goes with them: `hud.py` raises a frameless, always-on-top window
  (`/signin-hud`) in the **top-right corner of the screen**, like a system
  notification — it sits above the browser, reports success with the account,
  and offers a way back. Desktop only; `lodestone serve` falls back to the
  in-app card.
  **It is raised by the page, never by the API**: under `lodestone app --dev`
  the backend is a separate uvicorn process with no handle on the webview, so a
  backend-initiated window silently did nothing. The frontend always runs inside
  the webview, so it calls `window.pywebview.api.open_signin_hud(...)`
  (`desktop._AppBridge`). Anything that needs a native window must be driven from
  the page for the same reason. Timeout is **180s** (`hud.SIGNIN_TIMEOUT_SECONDS`), deliberately
  generous: an account switch with a password and 2FA blew past a 150s poll in
  practice. On expiry it shows an error with **Try again**, never a dead spinner.
- **Opening a panel must not block on subprocesses.** Building the model
  catalog shells out to vendor CLIs and probes local daemons; `/api/providers`
  and `/api/models/catalog` are *both* fetched every time the Models drawer
  opens. Measured uncached: **5.7s + 4.4s**, and the app had to be force-quit.
  The costs were ~50 Keychain reads (each spawning `security`),
  `detect_all_accounts()`, and `agent --list-models` (223 rows, 3.1s).
  `models/cache.py::ttl_cached` memoises the expensive probes — seconds for
  detection, minutes for CLI model lists — and `clear_provider_cache()` flushes
  the lot when a credential changes, so connecting is still instant. Warm drawer
  open: **0.05s**. Cheap probes (Gemini, ~60ms) stay uncached so nothing goes
  stale for no gain. **Profile before optimising** — SQLite and the window layer
  both looked guilty here and neither was.
- **Polling must be cheap.** `/auth/status` is polled every 2s during sign-in;
  `/refresh` re-runs discovery and takes **1.6-6.4s per provider**, so calling it
  each tick queued requests faster than the server could finish them, saturated
  FastAPI's sync threadpool, and froze the whole app (the UI shares that server).
  Poll the cheap endpoint and call the expensive one **once**, on success. CLI
  sign-in checks shell out, so they are cached for a few seconds
  (`reset_auth_cache()` on login and cancel).
- **A re-sign-in is not the old session.** Completion is the CLI's login
  *process exiting* (or the account visibly changing), never "the account looks
  authenticated" — which is already true when switching accounts and reported
  success on the first poll, before the user had touched the browser.
  `login_progress()` records who was signed in at start and compares.
  `AuthStatus`: **idle** = nothing in flight, **waiting** = a sign-in we started
  is running, **success** = it finished.
- - **Anything we spawn, we clean up — across runs.** A vendor CLI's `login`
  waits for a browser callback that may never arrive. Nothing reaped them, and
  the only handle lived in module state, so every launch forgot the previous
  launch's: **158 live `claude auth login` processes** were found on one machine,
  each holding memory and the vendor's OAuth callback port until sign-in stopped
  working and the app had to be force-quit. `models/login_processes.py` records
  every spawned login to disk (the process that must clean up is not the one
  that made the mess) and `run_app` reaps on launch *and* on quit. Only recorded
  PIDs are ever signalled, and each is re-checked against the command line we
  recorded first — PIDs get reused, and killing what inherited one is worse than
  the leak.
- **The webview origin is user state.** localStorage is keyed to it, so the port
  is not an implementation detail: a launch that lands on a different port loses
  the onboarding flag, the chosen model and the lead agent, and the app opens
  looking empty. `_reserve_port` binds the saved port the way uvicorn does
  (**SO_REUSEADDR** — without it a port the previous server just released, still
  holding connections in TIME_WAIT, reads as taken) and hands that socket
  straight to the server. Symptom when this broke: every *other* launch was
  empty.

**Anything the user starts, they can stop.** Sign-in is cancellable from both
  the floating card and the Models card: `/auth/cancel` → `AuthFlow.cancel()`
  terminates the CLI's login process. Dismissing the floating card cancels too —
  a close button that silently leaves work running is a lie.
- **Never make the user wait without telling them.** Long work runs as a
  background job with progress that survives a refresh — sync, brain enrich, CLI
  install. A spinner with no end state is a bug.
- **Never lose the user's state to our mistakes.** A stored model id that a
  provider retired is repaired, not fatal. A connection that cannot be used is
  reported, not silently dropped.
- **Assume nothing is installed and nothing is configured.** First launch, no
  keys, no CLIs, no accounts — the app must still open, explain itself, and
  offer a way forward.

- **Loopback is not a security boundary.** The API lists the user's home
  directory, stores provider credentials and can erase the brain, and it listens
  on `127.0.0.1` with no authentication — where every browser the user has open
  is also "on this machine". `api/security.py` refuses any request whose `Host`
  is not a loopback name (that is what ends DNS rebinding — the attacker
  controls the DNS, never the `Host` header), any cross-site `Sec-Fetch-Site`,
  and any request whose `Origin` does not match the `Host` it arrived on.
  **That last comparison is the one to get right.** The first version asked
  "is the `Origin` loopback?", which is a different question: a Vite server on
  `localhost:5173` or a notebook on `localhost:8888` passes it, and could
  therefore `POST /api/brain/reset`. Our own page is by definition served from
  the authority the request arrived on, so comparing the two distinguishes it
  from every other local origin without hardcoding a port — which matters,
  because the desktop app binds a different one per install. Deliberately
  **not** a token: against a local process it would live in a file that process
  can read, and against a browser it buys only what this comparison already
  buys.
  `/api/open-browser` takes `http(s)` only — otherwise it hands the system
  opener any scheme an installed app has registered.
- **Slow work gets its own lane, or it takes the window with it.** Every handler
  is a plain `def`, so they share one worker-thread pool — and the UI is served
  by the same server. `api/concurrency.py` gives model turns and provider probes
  bounded `CapacityLimiter`s and makes those endpoints `async`, so a queued
  probe holds **no** thread. Measured: with the shared pool throttled and 20
  blocking probes in flight, the UI waited **2.47s** without the lanes and
  answered immediately with them (`tests/test_threadpool_isolation.py`). This is
  the root cause behind the `/auth/status` freeze; polling something cheaper
  treated the symptom.
- **A failure we survive is still a failure we should be able to see.**
  `except Exception: pass` is correct at runtime and invisible afterwards, which
  is how "it just doesn't work" becomes unfalsifiable. Use
  `with suppressed("what you were attempting"):` from `lodestone/log.py` — same
  behaviour, keeps the evidence, and writes to a rotating file in the Lodestone
  home so a bug report has something in it. 57 sites were converted;
  `tests/test_failures_are_recorded.py` is what stops there being a 58th.
- **Every identifier we send a vendor is the vendor's or ours — never a third
  party's.** The ChatGPT sign-in sent `originator=opencode` and the xAI flow used
  OpenCode's client id: both told the vendor a different product was calling,
  and both made every user's sign-in breakable by a decision aimed at somebody
  else. The originator now matches the client it authenticates as, the xAI OAuth
  flow is gone (it could never yield a usable credential anyway — sign-in goes
  through the Grok CLI), and `tests/test_vendor_identity.py` scans for
  recurrences.
- **`"key" in row` on a `sqlite3.Row` tests the VALUES.** Not the keys. The graph
  store guarded every optional column that way, so the guards were always false
  and entity importance and confidence silently stayed at their defaults no
  matter what was stored — measured: importance stuck at 0.55 where it should
  have reached 0.7. Use `row.keys()`, or read the column directly when the
  schema guarantees it. `SIM118` and `SIM401` are disabled in `pyproject.toml`
  for exactly this reason; re-enabling either reintroduces the bug.

When in doubt: would a non-technical user understand what just happened, and
what to do next? If not, it is not finished.

## Run it
- `lodestone serve` → FastAPI on a browser tab.
- `lodestone app` → native desktop window (**pywebview / WKWebView**), server on a
  dynamic loopback port. This is the primary way users run it.
- **Dev / live-editing:** `lodestone app --dev` (or `lodestone serve --dev`) runs the
  backend with **uvicorn --reload**, so Python edits hot-reload. Cmd+R in the window
  only reloads the FRONTEND (assets are no-cache) — it can NOT reload Python, so
  without `--dev` a new/changed endpoint 404s until you relaunch. Frontend-only
  edits (html/js/css) always show on Cmd+R.
- Tests: `pytest`. Lint `ruff check lodestone tests`, types `mypy lodestone`.
  Python venv at `.venv` (use `./.venv/bin/python`).
- **Shipping it:** `scripts/build-dmg.sh` bundles, signs, notarises and staples a
  real `.dmg` (189 MB app → 74 MB image; torch is excluded deliberately).
  `scripts/build-macos-app.sh` is the *development* shim — its launcher runs this
  checkout's venv, so it works on this machine and nowhere else. Read
  [`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md) before touching either.

## Layout
- `lodestone/api/` — the HTTP surface. `app.py` is the composition root
  (middleware, lifespan, mounts); the routes live in `routes/`, grouped by
  subject and mounted from `ALL_ROUTERS`. Serves `/` (workspace) and
  `/onboarding`, mounts `/static`, and the `/api/*` JSON API.
- `lodestone/api/security.py` — the origin guard (Host / Origin /
  `Sec-Fetch-Site`). `lodestone/api/concurrency.py` — the bounded lanes slow
  handlers run in. `lodestone/api/schemas.py` — request bodies shared by more
  than one router.
- `lodestone/log.py` — `get_logger()` and `suppressed()`, the seam that replaced
  every silent `except: pass`.
- `packaging/` — the PyInstaller spec, the Hardened Runtime entitlements and the
  bundled app's launcher.
- `lodestone/hud.py` + `lodestone/web/signin_hud.html` — the floating sign-in
  card: one reused, transparent, frameless window that follows the user to the
  browser. Read [`docs/DESKTOP-SIGNIN.md`](docs/DESKTOP-SIGNIN.md) before
  changing it; nearly every line there is load-bearing for a bug that shipped.
- `lodestone/models/login_processes.py` — every vendor-CLI login we spawn, tracked
  to disk and reaped on launch and quit.
- `lodestone/web/` — the entire frontend, **vanilla JS, no build step**:
  - `index.html` + `app.js` + `styles.css` — the workspace.
  - `onboarding.html` — the self-contained cinematic onboarding (Connect → Build →
    Your Brain), inline `<style>`/`<script>` + an encoded brain point-cloud (`DATA`).
- `lodestone/brain/canonical/` — **the canonical Brain** (curated, source-backed
  model of the user) layered ABOVE the raw index + graph, in its own SQLite file
  `~/Library/Lodestone/brain.db` (raw index stays in `lodestone.db` — thousands of
  emails must never become "memory"). Modules: `db.py` (schema: entities /
  entity_identifiers / claims / events / evidence / tasks / candidates /
  evaluation_cases), `store.py` (CRUD + current-view), `redact.py` (secrets masked
  BEFORE extraction), `extract.py` (LLM + heuristic → *candidates only*),
  `curate.py` (**the trust core**), `freshness.py`, `recall.py`, `export.py`,
  `evaluation.py`, `service.py` (`get_canonical()` facade).
  **Trust rules (enforced in `curate.py`, never left to the model):** confirmed
  can supersede inferred, inferred NEVER supersedes confirmed; replacing a
  time-sensitive current claim requires a NEWER `source_timestamp`; tentative
  language → an `open` claim, never current; every accepted claim retains
  evidence; connector-sourced inferred facts go to the **review queue**, only
  `manual`/`chat` are high-trust. Claims are **append-only** — a change supersedes
  (never UPDATEs) the prior version and writes a Timeline event.
  Freshness only ages *time-sensitive* current claims; confidence is never
  lowered by age. Recall order is strict: **CANONICAL FACTS → graph → source
  excerpts** (`Brain.recall()` prepends the canonical block; failures are
  swallowed so curation can never break plain retrieval). Chat turns feed it via
  `learn_from_conversation` in `agents/runtime.py`, so the Brain keeps up with
  the conversation over time. Markdown/JSON mirror in `brain-export/` is a
  **generated projection, never a second source of truth**.
- `lodestone/brain/` — `brain.py` (store + graph facade + **enrichment**), `graph.py`,
  `extract.py`. **Knowledge graph = general enrichment pipeline** (works for ANY
  connector, incl. custom): memories carry a `graphed` flag; `Brain.enrich()` drains
  ungraphed memories → `clean_for_extraction()` (strip HTML/quotes/boilerplate/
  encoded blobs) → `is_graphable()` gate → **LLM extraction** (rich, precise, uses
  the caller's model) or the offline heuristic fallback, batched to cut calls.
  Automatic background pass after each sync is **heuristic (free)**; the richer
  **LLM pass is opt-in**. The LLM enrich runs as a **server-side job** (`Brain.
  start_enrich/stop_enrich/enrich_status`, `POST /api/brain/enrich/start|stop`,
  `GET /api/brain/enrich/status`) so a frontend refresh reconnects instead of
  killing it. `rebuild_graph()` clears the graph + re-queues everything. Never
  gate the graph on a hard-coded source allowlist — it's content-based & general.
    - **Brain v1.5 Foundation (Upgraded):**
      - **Schema & Persistence:** Memories carry `memory_type`, `source_id`, `event_time`, `valid_from`, `valid_until`, `importance`, `confidence`, `reinforcement_count`, `last_reinforced_at`, `last_accessed_at`, `access_count`, `status`, `extraction_method`, `supersedes_id`, `evidence`.
      - **Open Loops:** Dedicated `open_loops` table tracking commitments, follow-ups, and pending decisions with priority, due date, project/entity links, and lifecycle statuses (`open`, `waiting`, `blocked`, `completed`, `cancelled`, `stale`). Integrated into prompt auto-recall.
      - **Temporal Reasoning & Contradictions:** `detect_conflicts()` and non-destructive `resolve_conflict()` (`supersede()`) preserving full history when user changes preferences.
      - **Multi-Signal Hybrid Retrieval:** Semantic vector similarity + lexical match + importance + confidence + recency + temporal validity match + reinforcement log boost - status penalties. Returns `RecallExplanation` for transparent explainability.
      - **Security Guardrail:** Credentials and secrets are automatically redacted (`[REDACTED_KEY]`, `[REDACTED_PASSWORD]`, `[REDACTED_SECRET]`) on all memory ingest paths.
      - **Documentation:** See `docs/BRAIN-V1.5.md` for full specification.
  - **Recent-N cap (bulk sources):** the LLM enrich queue caps each BULK source
    (anything not in `Brain._FULL_SOURCES` = notes/agent/manual/notion/gcal) to its
    most-recent N items (`Brain.enrich_cap()`, default 100, stored in `meta.enrich_cap`,
    0 = unlimited) via a window-function query in `store.list_ungraphed/count_ungraphed`
    (`cap`/`full` args). High-signal sources always enrich in full. This is the
    dominant cost/time control — a first sync won't LLM-enrich thousands of old emails.
    `GET/POST /api/brain/enrich/config {cap}`; UI control in the Model drawer. The free
    heuristic pass is NOT capped (it drains everything so nothing is orphaned).
  - **Separate enrichment model:** enrichment can use a different provider/model from
    chat/agents — threaded as `model_name` through `enrich`/`start_enrich`/`extract_llm`.
    Client stores `lodestone_enrich_provider`/`lodestone_enrich_model` in localStorage
    (empty = "same as agent model", see `enrichModel()` in app.js); sent in the
    `/api/brain/enrich/start` body (`EnrichIn`). Lets users point enrichment at a
    cheap/local model while agents run a stronger one.
- **Token usage** (`lodestone/usage.py`): every model call via `get_provider()` is
  wrapped to record input/output tokens (estimated from length when the provider
  doesn't report), persisted in the `meta` table so it survives restarts/port
  changes. `GET /api/usage` (+ context-window "limit" from `registry.context_window`)
  → shown in the Model drawer; `POST /api/usage/reset`.
- `lodestone/connectors/` — one class per source (`gmail`, `gcal`, `gdrive`, `notion`,
  `github`, `linear`, `files`, `notes`, apple_*, `imessage`, custom). Registered in
  `connectors/__init__.py::REGISTRY`.
- `lodestone/agents/` — `presets.py` (Inbox/Launch/Research/Personal), `custom.py`
  (user + lead agents, SQLite), `runtime.py` (`run_turn`, auto-injects brain recall).
- `lodestone/models/` — LLM providers (`anthropic`, `openai`/`openrouter`/`ollama`,
  `claude-code`, `subscription`, `mock`) behind `LLMProvider`. `get_provider(name, model)`.
- `lodestone/scheduler.py` — background sync loop; `sync_all` is cooperative-cancelable.
- **Recall cost**: `store.search()` is linear in memory count (~0.05 ms each) and
  runs on *every* agent turn. 3k memories ≈ 120 ms, 10k ≈ 430 ms, 50k ≈ 2.5 s.
  95% of that is the eight-factor Python scoring loop, **not** vector search
  (the matmul is 0.1%). Measured and analysed in [`docs/SCALING.md`](docs/SCALING.md);
  reproduce with `scripts/benchmark_recall.py`. Don't reach for an ANN index —
  it would optimise the 0.1%.

## Model availability is resolved per user, never hardcoded
This is the rule that makes every user's experience match their own account
instead of whatever was true on a developer's machine when the code was written.

**Authority order** (`entitlements.evaluate_model_entitlement`, first answer wins):
1. **Connection.** Provider not connected → everything locked, `"Connect in Models"`.
2. **The provider's own answer** (`provider_reported=`): what *this account*
   says it can run — a live `/v1/models` query made with the user's credential,
   `~/.codex/models_cache.json` (ChatGPT plan), `~/.claude.json`
   `additionalModelOptionsCache` (Claude CLI), the installed Ollama tags. **This
   is the truth and the tables below never override it.**
3. **Static tier tables** (`_MODEL_TIER_REQUIREMENTS`) — a conservative guess
   used ONLY when step 2 has nothing to say: the user isn't connected, or
   discovery failed and a hardcoded fallback row is being shown.

So two users on different plans see different selectable models from the same
build: a ChatGPT Free account gets its slugs selectable and the Pro ones greyed
with a reason; a Pro account gets the opposite. Locked models stay **visible**
with a `plan_required` reason — never hidden.

**Hardcoded model lists are fallbacks, not truth.** `registry.MODEL_CATALOG`,
`discovery._fallback_*()` and `app.js::FALLBACK_CATALOG` exist only to render
something before a credential exists. Everything they produce is flagged
`is_fallback=True`, which is precisely what tells step 2 it has no provider
answer. The moment a credential is present, live discovery replaces them.
- Never add a model id to a fallback list without verifying it resolves.
  Retired ids are worse than a short list: they render as selectable and then
  fail at send time. (Audited 2026-09-12: 4 of 6 Claude ids, all 5 xAI ids, and
  the OpenRouter + Cursor defaults were dead.)
- `app.js::FALLBACK_CATALOG` is **generated** from `registry.MODEL_CATALOG` —
  regenerate it rather than hand-editing, so the two cannot drift.
- Never read another product's files (a competitor's app-support directory) to
  discover models or credentials.

**A stored model id is a request, not a guarantee.** Model choices persist (an
agent binding in `agent_model_configs`, `lodestone_model` in localStorage) while
provider catalogs move underneath them. `entitlements.resolve_usable_model()`
re-checks every request against what the account offers *now* and substitutes
the best model the user can run; `run_turn` calls it on the way to
`get_provider`, and repairs the agent's saved binding when that binding was the
stale one. A discovery failure never blocks a turn — the request is honoured.
Never send an id straight from storage to a provider.

**Detection is not consent.** Finding a CLI, a config file or a session on the
machine means we may *offer* it (`detected_account.found_on_computer` → a
"Continue" button). It never means connected: no code path may promote a
credential to CONNECTED, or treat a provider as `ready`, because a binary
happens to be installed.

**Credentials are independent.** A provider's account and its API key connect
and disconnect separately (`ProviderConnection.account_status` /
`api_key_status`, `set_credential(kind, status)`; `connection_status` is a
derived rollup). Removing a key must never sign the user out, and connecting an
account must never claim a key exists. `/api/providers/{name}/disconnect` takes
`scope=account|api_key|all`.

**We install the vendor CLIs ourselves** (`models/cli_manager.py`). Artifacts
are fetched **directly** — a vendor's install script is read as a *manifest*
(it names a version and a plain artifact URL) and never piped into a shell, so
the install is auditable, lands in our own directory, and cannot run arbitrary
code as the user. Downloads run as a background job with progress; a verify step
(`--version`) must pass before the binary is linked, and a failed download is
never linked. `find_*_cli()` prefers our pinned copy over anything on PATH.
Managed today: `cursor` (agent), `grok`. Adding one means adding a `CliSpec` and
a resolver.

**A CLI sign-in finishes on its own schedule.** The browser flow completes long
after any poll window, so: the waiting HUD polls `/auth/status` for **every**
provider (never a hardcoded id list), waits ~10 minutes, and on timeout says
what to do instead of vanishing — and **Refresh re-runs the flow's `status()`**,
which adopts a completed sign-in. Refresh must be able to finish a sign-in, not
just re-read state.

**A signed-in CLI is the identity.** Vendors also cache an account elsewhere —
the Cursor *app* keeps a different email in its sqlite — but the CLI is what we
actually run, so its `status` output wins. Read it from the shape the CLI
actually prints (`agent status --format json` nests identity under `userInfo`).

**Vendor CLIs own sign-in too, not just inference.** Each ships a `login`
command that opens the vendor's own consent page, because the OAuth client
belongs to that CLI — `agent login` → authenticator.cursor.sh, `grok login
--oauth` → accounts.x.ai ("Authorise Grok Build"), `claude auth login` →
claude.com. So a "Sign in with X" button spawns `X login` detached and polls a
status command (`agent status --format json`, `grok models`), marking the
account connected on success. That is the whole trick behind competing apps'
browser sign-in — no private client ids, no bundled secrets.

**Every subscription path is a vendor CLI.** None of these providers exposes a
subscription inference endpoint; each ships an official headless CLI instead,
and that is how a paid plan is reached:

| provider | CLI | headless invocation |
|---|---|---|
| Claude | `claude` | `claude -p --output-format json --model <id>` |
| Cursor | `agent` | `agent -p "<prompt>" --output-format json --model <id>` |
| xAI | `grok` | `grok -p "<prompt>" --output-format json -m <id>` |
| ChatGPT | `codex` | (we use the Codex responses endpoint directly) |

So "support provider X's subscription" almost always means "shell out to X's
CLI", not "find X's private API". Check for an official CLI first.

**A subscription is not an API key.** Per provider:
- **Claude** — no subscription inference endpoint, so an account-connected
  Claude with no key is delegated to the local Claude CLI
  (`AnthropicProvider._subscription_backend`).
- **ChatGPT** — no key → the Codex responses path.
- **Cursor** — has **no chat-completions API**. `api.cursor.com` is the
  admin/agent surface (`GET /v1/models` → 401 "Invalid User API Key"), but
  `POST /v1/chat/completions` → **404 Route not found**. Models run through the
  headless CLI, `agent -p "<prompt>" --output-format json --model <id>`
  (install: `curl https://cursor.com/install -fsS | bash`). `CURSOR_API_KEY`
  authenticates *that CLI* via env — it is not a REST credential, so a key
  alone cannot run anything. `find_cursor_cli()` verifies the binary really is
  Cursor's: `agent` is a generic name and a bare PATH hit is not trusted.
- **xAI** — a SuperGrok subscription covers grok.com and the mobile apps, and
  grants **no** credits on `api.x.ai`, which is the separately-billed developer
  API. An OAuth sign-in authenticates and then fails every request (including
  `GET /v1/models`) with 402 `personal-team-blocked:spending-limit`. So the
  OAuth token is NOT used as an API key: `XAIProvider._oauth_only` reports not
  ready with an explanation instead. Today xAI is `api_key_only` and needs an
  `XAI_API_KEY` from console.x.ai. The subscription path is xAI's official
  **Grok Build** CLI (`grok -p … --output-format json`) — not yet wired up; see
  **docs/ROADMAP.md → "Grok subscription support"**.

**A provider with no interactive sign-in is derived, never listed.**
`ProviderCapabilities.api_key_only` (no oauth/browser/device/CLI login) drives
both `/api/providers/{name}/signin` and whether the UI renders account and
sign-in cards. Don't reintroduce `providerId === "gemini"`-style checks in
`app.js` — add the capability and every surface follows.

Never send a subscription request to an API-key endpoint, and never let a
credential that merely *authenticates* be reported as ready.

**One sign-in protocol.** `models/auth_flows.py` is the single seam for every
provider sign-in: `get_flow(provider)` returns an `AuthFlow` with
`start() -> AuthStart` and `status() -> AuthStatus` (plus optional
`submit_code` / `cancel`). Routes are `POST /api/providers/{name}/auth/start`,
`GET …/auth/status`, `POST …/auth/code`, `POST …/auth/cancel`; the old
per-provider routes (`/signin`, `/{provider}/oauth-status`,
`/claude/submit-code`) are thin aliases. Which flow a provider gets is derived
from its capabilities — `api_key_only` → `ApiKeyOnlyFlow`, CLI-owned sign-in →
its own flow, otherwise `BrowserFlow`. **Adding a provider means registering a
flow, never adding a route or a UI branch.** A flow must always return a reason
rather than raise.

**The Models drawer is executed in tests, not just parsed.** Two node harnesses
under `tests/js/`, driven by `tests/test_models_drawer_render.py`:
- `render_provider_box.mjs` runs `renderProviderConnectBox` against a real
  `/api/models/catalog` payload and checks each provider's cards.
- `click_signin.mjs` runs the actual **click handler** and checks what lands on
  screen. Its DOM stub deliberately models detachment — reassigning `innerHTML`
  clears the subtree — because the bug it exists to catch was a card written
  into a container a preceding re-render had already replaced.

**A test must never start a real sign-in.** `flow.start()` and
`POST /api/providers/{name}/signin` reach `claude auth login`, which opens a
browser and then waits forever — and nothing reaped it, so **every pytest run
left one alive**. That, more than the app, is how 158 accumulated. `conftest.py`
swaps the argv of any `login` spawn for a command that exits immediately, so the
flows still run their real code with the vendor binary kept out; the guard is
itself covered, because a guard nobody exercises quietly stops working. This is
the third time test hygiene has bitten here — the others wrote to the real
Keychain and bound the fixed OAuth port 1455.

Neither `node --check` nor source-order assertions catch these: a temporal
dead-zone `ReferenceError` blanked the whole drawer and still passed
`node --check`, and the detached-container bug passed a source-order test. **If
you add a render path or a click handler, execute it in a test** — and when you
write the harness, verify it fails with the bug reintroduced before trusting it.

Two more ways these harnesses go blind, both learned the hard way:
- **Clicking is not covering.** `click_signin.mjs` existed and clicked the
  button, but every fixture short-circuited into the CLI branch — so the
  browser branch, where a second TDZ read of `floating` lived, never ran.
  Feed the harness an **explicit** `authStartResponse` per branch (see
  `BROWSER_FLOW`) instead of whatever `get_flow().start()` happens to return
  on this machine; one provider's real flow does not exercise the others.
- **Read the write, not the aftermath.** A handler's own `catch` calls
  `stopPolling()`, which re-renders the box and wipes the error it just set,
  so asserting on the final DOM sees a clean screen. The stub records every
  `textContent` write (`textWrites`); assert against that.

**Derive UI from capabilities, never from a provider-id chain.** Which cards a
provider gets comes from `api_key_only` / `has_interactive_signin`; badge text
comes from `isFoundOnComputer`; brand copy falls back to the provider's label.
Every `providerId === "x"` branch in a render path is a latent bug for the
provider that isn't in the chain — that is exactly how `claude-code` ended up
badged "Using this account" while it was only detected on the machine.

**macOS is the only supported platform.** Don't invest in Windows/Linux paths
or fallbacks; assume the Mac layout (`~/Library/…`, Homebrew, `security` for the
Keychain). Existing cross-platform branches can stay, but new work targets Mac.

**Provider errors are translated, never dumped.** `models/errors.py` holds one
taxonomy for every backend — `ErrorKind` (auth · billing · rate_limit ·
model_not_found · model_not_entitled · context_too_long · content_filtered ·
bad_request · server · network · timeout) and a `ProviderError` carrying an
actionable message, a redacted detail, and `retryable`.

- Classify at the boundary: `classify_http(provider, status, body, model=, key_env=)`
  for HTTP, `classify_exception(...)` for transport failures,
  `classify_cli(...)` for CLI-backed providers. Return `err.as_reply()`.
- **Status alone is not enough** — a 400 can be a bad model, an over-long
  context, a content filter or a billing block, so the body is inspected first.
- **Never surface raw provider JSON**, and never a credential: `redact()` strips
  `sk-…`, `xai-…`, `AIza…` and bearer tokens from anything user-visible.
- Messages name the provider's `display_name`, never its internal id.
- A model-level failure suggests models this user can actually run (via the live
  catalog, locked ones excluded).
- Providers sharpen a classified error by overriding `_refine_error(err)` —
  that is how xAI explains the subscription/API-credit split rather than saying
  a generic "out of credits".
- A `chat()` must **return** a `ChatResult`, never raise: an uncaught
  `raise_for_status()` is what turned a Claude 401 into a 500.

## The agent loop
*(Scored, not asserted: `lodestone/agents/evaluation.py` runs the real loop
against a scripted model — `GET /api/agents/evaluate`, or
`tests/test_agent_evaluation.py`, which fails if any capability breaks.)*

- **Effort is one gear selector, not a settings screen.** Low / Medium / High
  derive the tool budget, parallelism, verbatim history window, who writes the
  summary, delegation depth and recall size (`agents/effort.py`). Every one of
  those trades quality for cost in the same direction, and the model runs on the
  *user's* key or subscription — so a deeper loop spends their money. Low is a
  real choice: a 3B model given 24 rounds mostly finds 24 ways to go wrong.
- **Depth needs a memo and a stall detector.** A model with rounds left and
  nothing new to learn re-issues the same call forever. `agents/loop.py` answers
  a repeat from memory with a note to move on, and ends the turn after two
  rounds that learn nothing. Two cases, not one: the same call three times in
  *one* round is a wasteful model (run once, answer all three); the same call in
  a *later* round is a model that has stopped making progress.
- **Tool calls in a round run in parallel.** Safe because
  `sqlite3.threadsafety` is 3, every store opens `check_same_thread=False` under
  WAL with a busy timeout, and 60 concurrent mixed reads/writes across three
  stores produced no errors. Results are reassembled in request order — each has
  to match its `tool_call_id`.
- **Compress old turns, never drop them.** The window was six messages. Recent
  turns stay verbatim; older ones become a running summary that is *extended*,
  not rewritten (`agents/context.py`), so a long conversation does not
  re-summarise itself every message.
- **Delegation's guards are the feature** (`agents/delegation.py`). Depth from
  the effort profile, a sub-agent on half its parent's budget, and no agent
  twice in one chain. The chain lives in a `ContextVar` and tools run in a
  thread pool, which does **not** copy context — one `copy_context()` **per
  call** (a `Context` cannot be entered twice at once). Miss that and the other
  two guards are decoration. Refusals are returned as prose, not raised: the
  caller is a model.
- **A routine pre-authorises the routine, not the stranger who wrote the email
  it read.** `new_email` hands an agent text an attacker controls, and that text
  can contain an `<action type="send_email">`. Outbound actions therefore need a
  recipient on the user's explicit allow-list (`agents/permissions.py`);
  everything else queues for one tap (`agents/approvals.py`). Derived lists
  ("people you've emailed") were rejected — a stranger already in your inbox is
  exactly who an injection would name. Creating a routine is *never* unattended:
  it widens its own authority. **Interactive chat is not gated** — the Confirm
  button is a stronger signal, and a test fails if that path starts asking twice.
- **Streaming is a callback on the same loop, never a second loop.**
  `run_turn(on_event=…)`; a test asserts watching a turn does not change it.
  Two wire formats cover everything (`models/streaming.py`): Anthropic Messages
  (Claude API + Claude CLI's `stream_event` nesting + Grok CLI) and OpenAI
  chat-completions (OpenAI, OpenRouter, Ollama, DeepSeek, xAI, Gemini).
  `LLMProvider.stream()` defaults to yielding a whole `chat()` in one piece, so
  no caller ever branches on whether a backend can stream. CLI backends fall
  back when a stream yields no text — decided *before* emitting anything, since
  falling back afterwards would duplicate it. **In the browser, reassemble SSE
  frames across chunk boundaries**: one network chunk is not one frame, and a
  reader that assumes it passes every hand test and drops tokens for real.

## Keep everything general / device-independent
This app ships to many users on many machines. Do **not** bake in anything specific
to one person or one computer:
- **No hardcoded user data.** Persona/digest text, item counts, entity/theme names,
  agent names, sample content must be neutral placeholders filled at runtime from the
  real brain. (The digest cards in `onboarding.html` are neutral defaults; `fillCards`
  populates them.)
- **No absolute/user paths, accounts, or model keys** in code. Secrets live in
  `~/Library/Lodestone/secrets.json` via `settings.set_secret` / `get_secret`.
- **Frontend calls relative API paths** (`/api/...`, `/onboarding`, `/`). Never a host
  or port — the desktop app uses a random loopback port.
- **Fonts** use system stacks with fallbacks (`--sans`, `--mono` in `styles.css`);
  don't depend on a font only present on one OS.
- **Cross-platform keys**: use `e.metaKey || e.ctrlKey` and check `e.key`/`e.code`.

## The onboarding → workspace flow (built here)
Order: **Hero → Connect → Build → Digest → Workspace (welcome + lead agent)**.

- **Connect**: source grid from `GET /api/connectors`; an **AI Model** card
  (`openLLM`) picks a provider + optional key. Google sources are shown as
  disconnected until real sign-in (`/api/google/status` overrides the bundled-client
  `ready`). Clicking a source really connects it (Google OAuth / inline token /
  folder / custom form). **Continue requires Gmail connected AND an AI model chosen**
  (`canContinue()`), with a gold hint that narrows as each is satisfied.
- **Start-from-zero**: "Build my brain" calls `POST /api/brain/reset`
  (wipes memories+graph+connector state, clears connector secrets, disconnects Google)
  and clears local prefs, so it truly feels like a new user. A wiped/empty brain also
  redirects `/` → `/onboarding` once per session.
- **Build**: kicks `POST /api/sync/now`, then the progress bar **loads until the
  profile is extracted** — it waits for real data to land, then calls the digest.
  The bar never shows 100% (brain keeps building in the background). Cancel →
  `POST /api/sync/cancel` (cooperative). Never blocks on a full first sync.
- **Digest** ("Here's your brain"): cards stay hidden until
  `POST /api/brain/digest` returns, then fade in. Digest is **LLM-written** from the
  real brain and **uses the caller's provider/model** (passed in the body — the
  server default is `mock`). Computed counts+themes fallback + timeout so it never hangs.
- **Workspace welcome**: first entry (onboarded, no lead yet) shows "name your lead
  agent" → `POST /api/agents/lead` (system prompt personalised from the brain, pinned
  with a **Lead** badge) → `POST /api/agents/{id}/welcome` (one-time LLM intro that
  teaches the app; scripted fallback offline, not persisted).
- **Brain status**: header pill polls `/api/sync/status` + `/api/brain/stats`; clicking
  it opens the live "Your brain" panel (`#brainBuild`).

## Conventions
- **LLM provider is chosen client-side** and stored in `localStorage`
  (`lodestone_provider`, `lodestone_model`). Any endpoint that calls an LLM on behalf
  of the UI (`chat`, `welcome`, `digest`) accepts `provider`/`model` in the body and
  falls back to `settings.model_provider`. Provider API keys entered in the UI are
  saved via `POST /api/providers/{name}/key`; providers read them through
  `models/base.py::_saved_key` when the env var is unset.
- **localStorage keys**: `lodestone_onboarded`, `lodestone_lead_agent`,
  `lodestone_provider`, `lodestone_model`. `sessionStorage.ls_saw_onboarding` guards
  the empty-brain redirect.
- **Cmd/Ctrl+R** is bound in JS (both pages) to reload to the first screen — the
  webview doesn't wire the browser reload shortcut. Onboarding reloads to the hero;
  the workspace navigates to `/onboarding`.
- **The workspace** (`index.html`/`styles.css`/`app.js`) is a 3-column layout —
  agent rail (gradient **orb** avatars per agent, `orbStyle()`), chat (serif hero
  empty-state with quick-action cards + orb-avatar assistant messages + pill
  composer), and a right **Context / Tools** panel. The header brain
  pill and the sidebar **Brain** nav open the full-screen **Your Brain** screen
  (`openBrainScreen`, a self-contained canvas neural viz whose density tracks the
  memory count). Keep every element id — `app.js` injects into many of them
  (custom-app form, google card, secret form are built at runtime into modals).
- Adding a new pydantic body model used by a route: **define it above the route** —
  FastAPI resolves the annotation at decoration time.
- Git: never add a `Co-Authored-By: Claude` trailer to commits/PRs.

## Key API added for this flow
`POST /api/brain/reset` · `POST /api/brain/digest` · `POST /api/agents/lead` ·
`POST /api/agents/{id}/welcome` · `POST /api/providers/{name}/key` ·
`POST /api/sync/cancel`.

Model/provider API: `GET /api/models/catalog` · `GET /api/providers` ·
`POST /api/providers/{name}/auth/{start,status,code,cancel}` ·
`POST /api/providers/{name}/disconnect?scope=account|api_key|all` ·
`POST /api/providers/{name}/connect-local` · `POST /api/providers/{name}/refresh`.

## Working in this repo

### Pick the narrowest mode that solves the problem

**IMPLEMENT** · **REVIEW** · **DEBUG** · **TEST** · **AUDIT** · **PROFILE** ·
**DESIGN** · **INVESTIGATE**

Say which one you are in, and do not silently widen it. An AUDIT that starts
refactoring is no longer an audit — its findings are now entangled with its own
changes, and stop being trustworthy.

### Verification

The sequence, in order: **the focused test → the subsystem's suite → `pytest` →
`ruff check lodestone tests` → `mypy lodestone` → the `tests/js/` harnesses if
the frontend changed → `lodestone app` opens and renders.**

Baseline on `main`: **1425 passed, 18 skipped in ~62s**, `ruff` clean, `mypy`
clean over 113 files. Python venv at `.venv` — use `./.venv/bin/python`.

Run tests when stuck or finishing, not after every edit.

Four rules that were each bought the hard way:

- **Never weaken a test to get green**, never delete one that exposes an
  inconvenient architecture problem, and never skip the regression test on a bug
  fix.
- **A bug fix ships with a test that fails without it — and you must watch it
  fail.** A test written after the fix and never seen red is a guess about what
  it covers. Reintroduce the bug, confirm the red, restore. This has caught two
  blind harnesses in this repo that otherwise read as coverage.
- **`tests/api_surface.json` pins the HTTP surface.** A red `test_api_surface.py`
  means an endpoint moved. Fix the move, or move it deliberately and update the
  file in the same commit — never re-baseline it to get green.
- **A test must never start a real sign-in.** `conftest.py` swaps the argv of any
  `login` spawn, because the flows reach `claude auth login`, which opens a
  browser and waits forever. Nothing reaped them and **158 accumulated on one
  machine**. The guard is itself covered, because a guard nobody exercises
  quietly stops working.

### A change that spans two layers

Write the contract down before the code. These are the boundaries that exist,
and what each one has to name:

| boundary | the contract names |
|---|---|
| Frontend ↔ API | endpoint, request schema, response schema, error states, loading states, streaming behaviour |
| API ↔ agents | agent id, turn input, effort, event stream, `TurnResult`, errors |
| agents ↔ brain | recall context, memory writes, canonical learning, enrichment |
| agents ↔ models | model resolution, provider capabilities, streaming format, token accounting, auth state |
| models ↔ auth | `AuthFlow`: `start` / `status` / `code` / `cancel`, and the connection state it implies |
| connectors ↔ brain | source id, memory ingestion, metadata, sync lifecycle |

**Additive first.** Ship the new thing alongside the old, migrate the consumer,
then remove the old — three landings, never one. A rename landed on one side is
an outage on the other.

**And name a display string separately from an id.** The one contract defect
that reached the screen here was a row that carried an internal name and nothing
a person could read, so the consumer rendered the id. If a field crosses a layer
and a user will see it, the contract says which field they see.

### Git

- Commit style: lowercase type, then what a *user* gets — `fix(web): the model
  picker now changes which model actually answers`. Not what the code does.
- **Never add a `Co-Authored-By: Claude` trailer.**
- Small, focused commits, one behaviour each.
- **Always read `git diff` before finishing.** Every time.
- Commit or push only when the user asks.
