# Lodestone — working notes for Claude

Local-first AI **agent workspace**: a team of agents share one on-device "brain"
(memories + a knowledge graph) built from the user's connected sources. Bring your
own model. Everything runs and stays on the user's machine.

## Run it
- `lodestone serve` → FastAPI on a browser tab.
- `lodestone app` → native desktop window (**pywebview / WKWebView**), server on a
  dynamic loopback port. This is the primary way users run it.
- Tests: `pytest`. Python venv at `.venv` (use `./.venv/bin/python`).

## Layout
- `lodestone/api/app.py` — all HTTP routes (FastAPI). Serves `/` (workspace) and
  `/onboarding`, mounts `/static`, and the `/api/*` JSON API.
- `lodestone/web/` — the entire frontend, **vanilla JS, no build step**:
  - `index.html` + `app.js` + `styles.css` — the workspace.
  - `onboarding.html` — the self-contained cinematic onboarding (Connect → Build →
    Your Brain), inline `<style>`/`<script>` + an encoded brain point-cloud (`DATA`).
- `lodestone/brain/` — `brain.py` (store + graph facade), `graph.py`, extraction.
- `lodestone/connectors/` — one class per source (`gmail`, `gcal`, `gdrive`, `notion`,
  `github`, `linear`, `files`, `notes`, apple_*, `imessage`, custom). Registered in
  `connectors/__init__.py::REGISTRY`.
- `lodestone/agents/` — `presets.py` (Inbox/Launch/Research/Personal), `custom.py`
  (user + lead agents, SQLite), `runtime.py` (`run_turn`, auto-injects brain recall).
- `lodestone/models/` — LLM providers (`anthropic`, `openai`/`openrouter`/`ollama`,
  `claude-code`, `subscription`, `mock`) behind `LLMProvider`. `get_provider(name, model)`.
- `lodestone/scheduler.py` — background sync loop; `sync_all` is cooperative-cancelable.

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
  composer), and a right **Context / Tools** panel (`switchTab`). The header brain
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
