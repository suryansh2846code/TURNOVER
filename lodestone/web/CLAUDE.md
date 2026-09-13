# `lodestone/web/` — the frontend

Vanilla JS, **no build step**. `index.html` + `app.js` + `styles.css` are the
workspace; `onboarding.html` and `signin_hud.html` are self-contained pages.

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
