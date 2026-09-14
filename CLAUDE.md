# Lodestone — operating manual for coding agents

Local-first AI **agent workspace**: a team of agents share one on-device "brain"
(memories + a knowledge graph) built from the user's connected sources. Bring
your own model. Everything runs and stays on the user's machine. macOS only.

**One session works this repo at a time.**

This file is what you need on almost every task. It states rules; it does not
explain them at length — the explanation is in the document each rule points to,
and that document is the one to update when the rule changes.

- **Architecture, ownership, dependency direction, contracts** →
  [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Every code directory has its own `CLAUDE.md`** — it narrows this file for
  that directory and never contradicts it. If they disagree, this file wins and
  the directory note is wrong.
- **No rule is written in two places.** A duplicated rule drifts, and the copy
  that drifts is always the one you read.

---

## Run it

- `lodestone serve` → FastAPI on a browser tab.
- `lodestone app` → native desktop window (**pywebview / WKWebView**), server on
  a dynamic loopback port. This is how users run it.
- **Dev / live-editing:** `lodestone app --dev` (or `serve --dev`) runs the
  backend with **uvicorn --reload**, so Python edits hot-reload. Cmd+R in the
  window reloads only the FRONTEND — without `--dev` a new endpoint 404s until
  you relaunch. Frontend-only edits always show on Cmd+R.
- Tests `pytest` · lint `ruff check lodestone tests` · types `mypy lodestone`.
  Python venv at `.venv` — use `./.venv/bin/python`.
- Coverage: `pytest --cov --cov-report=term-missing`. No threshold, deliberately.
- **Shipping:** `scripts/build-dmg.sh` builds the real signed, notarised `.dmg`;
  `scripts/build-macos-app.sh` is a *development shim* that only works on this
  machine. Read [`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md) first.

## The map

| | |
|---|---|
| `api/` | the HTTP surface. `app.py` composes; routes live in `routes/` |
| `agents/` | the turn loop, tools, effort, delegation, approvals, permissions |
| `models/` | providers, auth flows, entitlements, discovery, CLI manager, errors |
| `brain/` | memories, graph, enrichment; `canonical/` is the curated layer |
| `connectors/` | one class per source, registered in `__init__.py::REGISTRY` |
| `core/` | SQLite store, schema, embeddings, chunking, dates |
| `web/` | the whole frontend. Vanilla JS, **no build step** |
| `desktop.py` · `hud.py` | the native window and the floating sign-in card |
| `config.py` · `log.py` | settings and logging. Leaf utilities — keep them that way |

Full ownership table and the allowed dependency direction:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §2–3.

---

## This is a product, not a developer tool

Lodestone ships to people who did not build it. **Every decision is a product
decision** — where "correct for an engineer" and "works for the person who
installed this" disagree, choose the second and make it correct underneath.

- **Never ask the user to open a terminal.** We download, pin and manage the
  vendor CLIs ourselves. One button, with progress. A copyable command is the
  fallback, never the plan.
- **Never show a control that cannot work.** A sign-in button that teaches us
  nothing, a model that 404s when selected, a "Connected" badge with no
  credential — each shipped here, and each read as "the app is broken".
- **Never surface an internal.** No raw provider JSON, no stack traces, no
  internal ids in user-facing text. Errors say what happened and what to do.
- **Anything the user starts, they can stop.** Sign-in, sync, enrichment. A
  close button that silently leaves work running is a lie.
- **Never make the user wait without telling them.** Long work is a background
  job with progress that survives a refresh. A spinner with no end state is a bug.
- **Never lose the user's state to our mistakes.** A retired model id is
  repaired, not fatal. An unusable connection is reported, not dropped.
- **Assume nothing is installed and nothing is configured.** First launch, no
  keys, no CLIs, no accounts — it must still open and explain itself.

When in doubt: would a non-technical user understand what just happened, and
what to do next? If not, it is not finished.

---

## Invariants

Load-bearing. Each was bought by a shipped bug. Breaking one is a regression
even when every test is green. Reasoning and measurements:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §7.

**Security — `api/`**
- The origin guard compares `Origin` to the `Host` it arrived on. **Never** "is
  `Origin` loopback" — a Vite server on `localhost:5173` passes that and could
  `POST /api/brain/reset`. Deliberately not a token.
- `/api/open-browser` takes `http(s)` only, or it hands the system opener any
  scheme an installed app registered.
- Loopback is not a security boundary: every browser the user has open is also
  "on this machine".

**Concurrency — `api/`**
- Slow handlers run in a bounded lane (`@calls_a_model`, `@probes_a_provider`)
  and are `async`, so a queued one holds **no** worker thread. Without this, 20
  blocking probes made the UI wait 2.47s.

**Desktop — `desktop.py`, `hud.py`** · [`docs/DESKTOP-SIGNIN.md`](docs/DESKTOP-SIGNIN.md)
- **The webview origin is user state.** localStorage is keyed to it, so the saved
  port is bound with `SO_REUSEADDR` and handed to the server. When this broke,
  every *other* launch opened empty.
- A native window is raised **by the page**, never by the API — under `--dev` the
  backend is a separate process with no handle on the webview.
- Showing the card must not activate the app (`orderFrontRegardless`, not
  `activateIgnoringOtherApps_`). Every Cocoa mutation goes through
  `AppHelper.callAfter`, or the process hangs.
- **Anything we spawn, we clean up — across runs.** Every vendor login is
  recorded to disk and reaped on launch *and* quit; only recorded PIDs are
  signalled, each re-checked against the command line recorded with it. 158 live
  `claude auth login` processes were once found on one machine.

**Models — `models/`** · [`docs/development/models.md`](docs/development/models.md)
- **Model availability is resolved per user, never hardcoded.** Connection → the
  provider's own answer for this account → static tables. Shipped lists are
  fallbacks flagged `is_fallback=True`.
- **A stored model id is a request**, re-checked before use. Never send one
  straight from storage to a provider.
- **Detection is not consent.** A binary on the machine lets us *offer* it and
  never marks it connected.
- **Every identifier we send a vendor is the vendor's or ours** — never a third
  party's. Sending `originator=opencode` made every user's sign-in breakable by
  someone else's decision.
- A `chat()` returns a `ChatResult`, never raises. Errors are classified and
  translated, never dumped.
- Credentials are independent: removing a key must not sign the user out.

**Brain and storage — `brain/`, `core/`**
- **`"key" in row` on a `sqlite3.Row` tests the VALUES, not the keys.** Use
  `row.keys()`. `SIM118`/`SIM401` are disabled in `pyproject.toml` for exactly
  this reason; re-enabling either reintroduces the bug.
- Claims are **append-only** — a change supersedes, never `UPDATE`s. Inferred
  never supersedes confirmed.
- Recall order is canonical facts → graph → source excerpts, and a curation
  failure can never break plain retrieval.
- Graph enrichment is content-based. **Never gate it on a connector allowlist.**

**Agents — `agents/`** · [`docs/AGENTS.md`](docs/AGENTS.md)
- **A routine pre-authorises the routine, not the stranger who wrote the email it
  read.** Outbound actions need a recipient on the explicit allow-list; a derived
  list is exactly what an injection would name. Interactive chat is deliberately
  not gated.
- Streaming is a callback on the same loop, never a second loop.
- Delegation guards live in a `ContextVar`: one `copy_context()` **per call**,
  and the chain is left on every exit path.

**Frontend — `web/`**
- **Escape before applying inline markdown**, the way `md()` does. The link
  regex is safe only because quotes are already `&quot;`.
- Relative API paths only. Never a host or port.
- Derive UI from capabilities, never from a `providerId === "x"` chain.
- **`app.js` cannot become an ES module** — the test harnesses evaluate it with
  `new Function`. Read
  [`docs/development/frontend-testing.md`](docs/development/frontend-testing.md)
  before splitting anything.

**Everywhere**
- `except Exception: pass` is invisible afterwards. Use
  `with suppressed("what you were attempting"):` from `lodestone/log.py`.

---

## Keep everything general / device-independent

Many users, many machines. Do not bake in anything specific to one of either.

- **No hardcoded user data.** Persona text, counts, entity names, agent names and
  sample content are neutral placeholders filled at runtime from the real brain.
- **No absolute or user paths, accounts, or model keys** in code. Secrets live in
  `~/Library/Lodestone/secrets.json` via `settings.set_secret` / `get_secret`.
- **Frontend calls relative paths** — the desktop app uses a random loopback port.
- **Fonts** use system stacks with fallbacks (`--sans`, `--mono`).
- **Cross-platform keys**: `e.metaKey || e.ctrlKey`, and check `e.key`/`e.code`.

---

## Conventions

- **The LLM provider is chosen client-side** and stored in localStorage
  (`lodestone_provider`, `lodestone_model`). Any endpoint that calls an LLM for
  the UI (`chat`, `welcome`, `digest`) accepts `provider`/`model` in the body and
  falls back to `settings.model_provider`. Keys entered in the UI are saved via
  `POST /api/providers/{name}/key`; providers read them through
  `models/base.py::_saved_key` when the env var is unset.
- **localStorage keys**: `lodestone_onboarded`, `lodestone_lead_agent`,
  `lodestone_provider`, `lodestone_model`; `sessionStorage.ls_saw_onboarding`
  guards the empty-brain redirect.
- **Cmd/Ctrl+R** is bound in JS on both pages — the webview does not wire it.
- **The workspace** is a 3-column layout: agent rail (gradient orb avatars), chat,
  and a right Context/Tools panel. **Keep every element id** — `app.js` injects
  into many of them.
- A pydantic body model used by a route must be **defined above** it — FastAPI
  resolves the annotation at decoration time.
- Adding an endpoint means adding a line to `tests/api_surface.json`, in the same
  commit, deliberately.
- The onboarding → workspace flow:
  [`docs/development/onboarding-flow.md`](docs/development/onboarding-flow.md).

---

## Working in this repo

### Pick the narrowest mode that solves the problem

**IMPLEMENT** · **REVIEW** · **DEBUG** · **TEST** · **AUDIT** · **PROFILE** ·
**DESIGN** · **INVESTIGATE**

Say which one you are in, and do not silently widen it. An AUDIT that starts
refactoring is no longer an audit — its findings are now entangled with its own
changes and stop being trustworthy.

### Verification

In order: **the focused test → the subsystem's suite → `pytest` →
`ruff check lodestone tests` → `mypy lodestone` → the `tests/js/` harnesses if
the frontend changed → `lodestone app` opens and renders.**

Baseline in CI: **1440 passed, 20 skipped**, ruff clean, mypy clean over 114
files, coverage 76%. Locally the split differs — some tests skip when a provider
is genuinely connected on the machine. Run tests when stuck or finishing, not
after every edit. Details: [`tests/CLAUDE.md`](tests/CLAUDE.md).

Four rules, each bought the hard way:

- **Never weaken a test to get green**, never delete one that exposes an
  inconvenient architecture problem, never skip the regression test on a fix.
- **A bug fix ships with a test that fails without it — and you must watch it
  fail.** Reintroduce the bug, confirm red, restore. A test written after the fix
  and never seen red is a guess about what it covers.
- **`tests/api_surface.json` pins the HTTP surface.** A red `test_api_surface.py`
  means an endpoint moved. Never re-baseline it to get green.
- **A test must never start a real sign-in.** `conftest.py` swaps the argv of any
  `login` spawn. The guard is itself covered, because a guard nobody exercises
  quietly stops working.

### A change that spans two layers

**Write the contract down before the code**, and land both sides together with a
test that fails if only one of them ships. Two halves that each pass their own
tests can still be wrong about each other, and that is not hypothetical here.

**Additive first.** Ship the new thing beside the old, migrate the consumer, then
remove the old — three landings, never one. And **name a display string
separately from an id**: if a field crosses a layer and a person will read it,
the contract says which field they read.

The boundaries and what each must name:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §4.

### Things to never do

- Add a model id to a fallback list without verifying it resolves.
- Read another product's app-support directory for credentials or models.
- Add a `providerId === "x"` branch to a render path.
- Gate graph enrichment on a connector-name allowlist.
- Promote a detected credential to connected.
- Invest in Windows/Linux paths. macOS is the only supported platform.
- Add a `Co-Authored-By: Claude` trailer to a commit or PR.

### Git

- Commit style: lowercase type, then what a *user* gets — `fix(web): the model
  picker now changes which model actually answers`. Not what the code does.
- Small, focused commits, one behaviour each.
- **Always read `git diff` before finishing.** Every time.
- Commit or push only when asked.

---

## Where to look when

| you need | read |
|---|---|
| who owns what, and what may import what | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| why a decision was made | [`docs/DECISIONS.md`](docs/DECISIONS.md) |
| measured complexity and known duplication | [`COMPLEXITY_AUDIT.md`](COMPLEXITY_AUDIT.md) |
| the agent loop in depth | [`docs/AGENTS.md`](docs/AGENTS.md) |
| providers, entitlements, auth, errors, streaming | [`docs/development/models.md`](docs/development/models.md) |
| what was slow and what fixed it | [`docs/development/performance.md`](docs/development/performance.md) |
| recall cost at scale | [`docs/SCALING.md`](docs/SCALING.md) |
| the macOS window and sign-in card | [`docs/DESKTOP-SIGNIN.md`](docs/DESKTOP-SIGNIN.md) |
| why `app.js` cannot be split yet | [`docs/development/frontend-testing.md`](docs/development/frontend-testing.md) |
| the first-run flow | [`docs/development/onboarding-flow.md`](docs/development/onboarding-flow.md) |
| the brain's data model | [`docs/BRAIN-V1.5.md`](docs/BRAIN-V1.5.md) |
| connectors | [`docs/CONNECTORS.md`](docs/CONNECTORS.md) |
| driving a real browser (planned) | [`docs/BROWSER.md`](docs/BROWSER.md) |
| building and shipping | [`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md) |
| known gaps | [`docs/AUDIT.md`](docs/AUDIT.md) |
