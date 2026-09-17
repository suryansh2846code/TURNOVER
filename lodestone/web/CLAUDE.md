# `lodestone/web/` — the frontend

Vanilla JS, **no build step**. The workspace is `index.html` + `styles.css` +
twelve plain scripts; `onboarding.html` and `signin_hud.html` are self-contained
pages.

**`index.html` declares the script order, and that is the only place it is
written down.** The browser and the test harnesses both read it from there.
Order is the dependency graph — `core.js` first, `app.js` last — and a `const`
read before its definition is a temporal dead-zone `ReferenceError` that
`node --check` passes.

| file | owns |
|---|---|
| `core.js` | `$` `api` `esc` `md` `toast`, the orb palette, the icon set |
| `providers.js` | the catalog and its state, sign-in, the provider cards |
| `models.js` | the model picker, agent bindings, `loadProviders()` |
| `chat.js` | sending a turn, and everything that renders one |
| `brain.js` | the brain panel, sync, Google, entity and search modals |
| `connectors.js` | adding a source, and setting one up |
| `workspace.js` | approvals, tasks, reminders, routines, first-run |
| `brain-screen.js` | the full-screen canvas view |
| `usage.js` | the token meter and enrichment progress |
| `library.js` | the Agent Library screen — templates, shelves, the roster |
| `tools.js` | the Agents & tools panel — what one agent may use, with switches |
| `app.js` | the shell: state, chrome, agent rail, nav, keyboard, boot |

**Before moving code between them**, read the five checks in
[`docs/development/frontend-testing.md`](../../docs/development/frontend-testing.md)
— and grep for who reads the file you are moving out of. A test that greps one
script out of eleven does not fail; it passes.

- **Every left-nav item opens a screen.** The slide-over drawer is gone:
  `tasks` moved into Inbox and `tools` became the Agents & tools panel, and
  those were its only two occupants. `openDrawer()` kept its name — four call
  sites use it — and is now pure routing. `tests/js/open_model_screen.mjs`
  reads the nav list out of `index.html` and clicks every item.
- **Icons are drawn, never typed.** No emoji, and no dingbat standing in for a
  control: `IC` in `core.js` is the set. An emoji is a colour font the OS
  picks, so it ignores `currentColor` — it cannot take the gold accent, it sits
  at its own weight beside every drawn icon, and it changes shape between macOS
  versions. A typographic arrow *inside a sentence* ("Add agent →", "System
  Settings → Privacy") is not an icon and stays; the design brief asks for it.
- Relative API paths only (`/api/…`). Never a host or port — the desktop app
  binds a different loopback port per install.
- `Cmd+R` reloads the frontend only. It cannot reload Python; without `--dev` a
  new endpoint 404s until you relaunch.
- **If you add a render path or a click handler, execute it in a test**
  (`tests/js/`). `node --check` passes on the temporal-dead-zone `ReferenceError`
  that blanked the whole drawer, and a source-order assertion passed while a card
  was being written into a detached container.
- Derive UI from capabilities, never from a `providerId === "x"` chain.
- Any new `innerHTML` path must escape *before* applying inline markdown, the way
  `md()` does.

Rules for all of it: [`/CLAUDE.md`](../../CLAUDE.md).
