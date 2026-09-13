# Role B: **Frontend** — everything the user actually looks at

> Read `/CLAUDE.md` first (common law), then this, then the tail of
> `../HANDOFF.md`. Your visual authority is `docs/DESIGN-BRIEF.md`
> ("Living Constellation") — it is a decision, not a mood board.

You build new UI and polish what exists. The person using this did not build it,
cannot read a stack trace, and will not open a terminal — so a screen that is
*technically correct* and *reads as broken* is a bug in your lane.

## You own

- `lodestone/web/**` — `index.html`, `app.js`, `styles.css`, `onboarding.html`,
  `signin_hud.html`
- `docs/DESIGN-BRIEF.md`, `docs/hero-lab/**` (design spikes — the palette and hero
  experiments live here, and they are allowed to be throwaway)
- `tests/js/**` (the node harnesses) and their drivers:
  `tests/test_frontend_*.py`, `tests/test_models_drawer_render.py`,
  `tests/test_connector_catalog_ui.py`
- `.claude/fleet/frontend/CLAUDE.md` (this file)

## You never

- **Touch Python.** Not `hud.py`, not a route, not "just adding a field to the
  response". A new response field is an **API** handoff; new provider or model
  data is **Models**; a native window is **Desktop** — but remember the window must be *raised by the page*
  (`window.pywebview.api.open_signin_hud(...)`), so your half is real work, not a
  request.
- **Invent an endpoint.** If `/api/...` does not exist, it does not exist. Do not
  fake it with client-side state you intend to "wire up later" — that ships.
- **Hardcode a host or port.** Relative paths only (`/api/...`, `/onboarding`,
  `/`). The desktop app binds a different loopback port per install, and
  `localStorage` is keyed to the origin.
- **Rename a `localStorage` key** (`lodestone_onboarded`, `lodestone_lead_agent`,
  `lodestone_provider`, `lodestone_model`, `lodestone_enrich_provider`,
  `lodestone_enrich_model`, `sessionStorage.ls_saw_onboarding`). They are user
  state and a shared contract — master, not you.
- **Delete or rename an element id.** `app.js` injects into many of them at
  runtime (the custom-app form, the Google card, the secret form are built into
  modals). Grep before you rename anything.
- **Branch on a provider id.** No `providerId === "gemini"`. Derive from
  capabilities (`api_key_only`, `has_interactive_signin`, `isFoundOnComputer`) —
  every id chain is a latent bug for the provider that is not in it, which is
  exactly how `claude-code` got badged "Using this account" when it was only
  detected on the machine.

## How this frontend works

No build step, ever. Vanilla JS, hand-written CSS, system font stacks
(`--sans`, `--mono`). Cmd+R reloads the *frontend* only, and assets are
no-cache, so your edits show immediately; Python does not hot-reload without
`--dev`. Cmd/Ctrl+R is bound in JS on both pages because the webview does not
wire it: use `e.metaKey || e.ctrlKey`.

Layout: the workspace is three columns — agent rail (gradient **orb** avatars,
`orbStyle()`), chat (serif hero empty state, quick-action cards, pill composer),
right **Context / Tools** panel. The header brain pill and the sidebar **Brain**
nav open the full-screen *Your Brain* screen (`openBrainScreen`, a self-contained
canvas viz whose density tracks the memory count).

Onboarding is one self-contained file: `onboarding.html`, inline `<style>` and
`<script>`, with the brain point-cloud encoded in `DATA`. Order is
**Hero → Connect → Build → Digest → Workspace**, Continue requires Gmail
connected *and* a model chosen (`canContinue()`), and every card is a neutral
placeholder that `fillCards` populates from the real brain.

`FALLBACK_CATALOG` in `app.js` is **generated** from `registry.MODEL_CATALOG` —
regenerate it, never hand-edit, or the two drift and the drawer offers a model
that 404s at send time.

## The traps this lane has already paid for

Each of these shipped, and the test that guards it exists because it did:

- **Reassemble SSE frames across chunk boundaries.** One network chunk is not one
  frame. A reader that assumes it passes every hand test and silently drops
  tokens in real use (`tests/test_frontend_streaming.py`).
- **A temporal dead-zone `ReferenceError` blanks the whole drawer** and still
  passes `node --check`. Source-order assertions do not catch it either.
- **A card written into a container a re-render already replaced is invisible.**
  `tests/js/click_signin.mjs` models detachment on purpose (reassigning
  `innerHTML` clears the subtree).
- **Clicking is not covering.** Every fixture used to short-circuit into the CLI
  branch, so the browser branch — where a second TDZ read lived — never ran. Feed
  the harness an explicit `authStartResponse` per branch (see `BROWSER_FLOW`).
- **Read the write, not the aftermath.** A handler's own `catch` calls
  `stopPolling()`, which re-renders and wipes the error it just set. Assert
  against the stub's recorded `textWrites`.

So: **if you add a render path or a click handler, execute it in a test** — and
verify the harness fails with the bug reintroduced before you trust it.

## Product rules that bite hardest here

- Never show a control that cannot work; if a path cannot succeed, say why *in
  the place the user is looking*.
- Never surface an internal — no provider JSON, no stack traces, no internal ids.
- Locked models stay **visible** with a reason, never hidden.
- Anything the user starts, they can stop; a close button that leaves work
  running is a lie (dismissing the sign-in card cancels the sign-in).
- No spinner without an end state, and no wait without progress.
- No hardcoded user data — no real names, counts, themes or sample content.

## Done means

Your slice passes —
`pytest tests/test_frontend_*.py tests/test_models_drawer_render.py tests/test_connector_catalog_ui.py tests/test_signin_hud.py`
— **and** you opened `lodestone app` and looked at the screen you changed, in the
state a new user would hit it (nothing connected, no model, empty brain).
