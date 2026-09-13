# Role: **macOS Desktop** *(dormant specialist — activated per task)*

> Read `/CLAUDE.md`, then **`docs/DESKTOP-SIGNIN.md` in full** before touching
> `hud.py`: nearly every line there is load-bearing for a bug that shipped. Then
> `docs/DISTRIBUTION.md` before touching the build. Then `../HANDOFF.md`.

`lodestone app` — pywebview / WKWebView with the server on a dynamic loopback
port — is how users actually run this. macOS is the only supported platform; new
work does not target Windows or Linux.

## You own

`lodestone/desktop.py`, `lodestone/hud.py`, `packaging/**` (the PyInstaller spec,
Hardened Runtime entitlements, the bundled launcher), `scripts/build-*.sh`,
`docs/DESKTOP-SIGNIN.md`, `docs/DISTRIBUTION.md`, `tests/test_signin_hud*.py`,
`tests/test_desktop_port.py`.

`web/signin_hud.html` is **Frontend's** file — you consume it (seam 4).

## The rules, all of them paid for in shipped bugs

- **A floating card is a Spaces problem, not a z-order problem.** With default
  collection behaviour a window belongs to the Space it was created on.
  `_apply_float_behaviour` sets `CanJoinAllSpaces | FullScreenAuxiliary`, drops to
  **`NSFloatingWindowLevel`** (status level claimed system UI it has no business
  covering) and sets `hidesOnDeactivate = False`. **Not** `Stationary` — that pins
  to screen coordinates during Space transitions and is redundant once a window
  joins every Space.
- **Known macOS limit, measured:** nothing reaches another app's *full-screen*
  Space. Levels 3, 25 and 101, with and without `Stationary`, with an accessory
  activation policy — all fail. Alfred and Raycast manage it as `LSUIElement`
  accessory apps with a non-activating `NSPanel`; pywebview creates a plain
  `NSWindow`, and making Lodestone dockless is not a trade worth this. The in-app
  row in the Models panel is the fallback, which is why it stays on screen anyway.
- **Showing the card must not activate the app.** `makeKeyAndOrderFront_` +
  `activateIgnoringOtherApps_` yanks keyboard focus out of the browser the user is
  signing into — every time the card updates. Use `orderFrontRegardless()`.
- **Every Cocoa mutation goes through `AppHelper.callAfter`.** Calling these
  setters from the js_api worker thread hangs the process.
- **Position against `NSScreen.visibleFrame`, on the screen under the pointer.**
  `webview.screens[0]` is the primary display's *full* frame — wrong monitor on a
  multi-display desk, and it ignores the menu bar and Dock. Points, not pixels.
- **The window is raised by the page, never by the API.** Under
  `lodestone app --dev` the backend is a separate uvicorn process with no handle on
  the webview, so a backend-initiated window silently did nothing.
- **Timeout is 180s** (`SIGNIN_TIMEOUT_SECONDS`), deliberately generous — an
  account switch with a password and 2FA blew past a 150s poll in practice. On
  expiry: an error with **Try again**, never a dead spinner.
- **The webview origin is user state.** `localStorage` is keyed to it, so a launch
  on a different port loses onboarding, the chosen model and the lead agent, and
  the app opens looking empty. `_reserve_port` binds the saved port with
  **SO_REUSEADDR** (without it a port still holding TIME_WAIT connections reads as
  taken) and hands that socket to the server. Symptom when this broke: every
  *other* launch was empty.
- **Reap what we spawn, on launch and on quit** — `run_app` does both.
- `scripts/build-dmg.sh` bundles, signs, notarises and staples a real `.dmg`
  (189 MB app → 74 MB image; torch excluded deliberately).
  `scripts/build-macos-app.sh` is a **development shim** whose launcher runs this
  checkout's venv — it works on this machine and nowhere else.

## Open, assigned to you

`docs/ROADMAP.md` item 2 — **Full Disk Access handling**. The largest gap between
"the `.dmg` builds" and "the `.dmg` works for a stranger". Needs Connectors
(honest capability reporting) and Frontend (the explainer).

## Done means

`pytest tests/test_signin_hud*.py tests/test_desktop_port.py` green, then the full
sequence — **and you launched the real app**, switched Spaces, and watched the card
follow. No test in this repo can prove that part.
