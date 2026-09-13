# Desktop sign-in — the floating card, and everything that fought it

> How a browser sign-in is presented on the desktop, and the record of what went
> wrong getting there. Companions: [`DECISIONS.md`](DECISIONS.md) (the crisp
> "why"), [`CLAUDE.md`](../CLAUDE.md) (the rules these findings became).
>
> Read this before touching `hud.py`, `signin_hud.html` or `desktop.py`. Most of
> what is below is **measured**, not reasoned — and several of the obvious
> explanations turned out to be wrong.

---

## The shape of it

A browser sign-in takes the user out of Lodestone, so the status follows them: a
small always-on-top card in the top-right of the screen, like a system
notification. It reports progress, offers **Cancel**, and says so when it works.

| piece | file | job |
|---|---|---|
| the window | `lodestone/hud.py` | create once, configure, place, raise, resize, hide |
| the card | `lodestone/web/signin_hud.html` | the UI, the poll loop, self-measurement |
| the bridge | `lodestone/desktop.py` (`_AppBridge`) | what the page can call |
| the flows | `lodestone/models/auth_flows.py` | per-provider sign-in, unchanged by any of this |
| the cleanup | `lodestone/models/login_processes.py` | reap CLI logins we spawned |

**The window is raised by the page, never by the API.** Under
`lodestone app --dev` the backend is a separate uvicorn process with no handle on
the webview, so a backend-initiated window silently does nothing. The frontend
always runs inside the webview, so it calls
`window.pywebview.api.open_signin_hud(...)`.

**One window, created hidden, reused forever.** `prepare()` builds it on the main
thread before `webview.start()`; `open_signin()` reloads its URL and shows it.
That is why an update changes the existing card and a second one cannot appear.

**Every Cocoa mutation goes through `AppHelper.callAfter`.** The js_api bridge
runs on a worker thread; calling `setLevel_`/`setFrame_` from there hangs the
process. This was diagnosed the hard way — a probe that looked like a deadlock.

**Placed against `NSScreen.visibleFrame`, on the screen under the pointer.**
`webview.screens[0]` is the *primary* display's **full** frame, which is wrong
twice over: it puts the card on the wrong monitor at a multi-display desk, and
it ignores the menu bar and the Dock, so "top-right of the screen" lands
underneath the menu bar. `visibleFrame` is the usable area of the screen the
user is actually looking at. Cocoa reports it in points, not pixels, so Retina
and mixed-scale arrangements need no special case at all.

**Timeout is 180s** (`hud.SIGNIN_TIMEOUT_SECONDS`), deliberately generous: an
account switch with a password and 2FA blew past a 150s poll in practice. On
expiry the card shows an error with **Try again** — never a dead spinner.

---

## What went wrong, in order

Each of these shipped. Each has a test that fails if it comes back.

### 1. The card disappeared when the user switched to the browser

**Symptom:** "it is still not overlapping other apps." Switch to Chrome and the
card is gone.

**Wrong guess (mine, twice):** the window level is too low. It was not — pywebview's
`on_top` already set `NSStatusWindowLevel` (25), above every normal window.
*Raising* the level could not have helped, and in fact we ended up **lowering** it.

**Real cause:** `collectionBehavior == 0` (`NSWindowCollectionBehaviorDefault`).
A window with the default collection behaviour belongs to **the Space it was
created on**. Measured: `onActiveSpace` flipped to `False` the moment another app
came forward. The card was never behind anything — it was on another Space.

**Fix:** `CanJoinAllSpaces | FullScreenAuxiliary`, and the level dropped to
`NSFloatingWindowLevel` (3) — still above every app's normal windows, no longer
covering the menu bar and system UI, which a sign-in card has no business
claiming. `hidesOnDeactivate` set explicitly `False`.

**`Stationary` is deliberately not set.** It pins a window to screen coordinates
during Space transitions — that is for wallpaper-like overlays — and it is
redundant once a window joins every Space. Tested; it changed nothing.

**Verified:** with the card up and another app active, the window server's
front-to-back list shows **nothing** drawn above it except system UI.

### 2. …but not over another app's full-screen Space *(open limitation)*

Measured, not assumed. With a full-screen browser frontmost:

| level | collection behaviour | activation policy | on the active Space? |
|---|---|---|---|
| floating (3) | allSpaces \| aux | regular | no |
| status (25) | allSpaces \| aux | regular | no |
| popUpMenu (101) | allSpaces \| aux | regular | no |
| floating (3) | allSpaces \| aux \| **stationary** | regular | no |
| floating (3) | allSpaces \| aux | **accessory** | no |

The collection behaviour *was* applied (read back as 257 / 273 / 1). macOS simply
will not place the window there. Apps that manage it (Alfred, Raycast) are
`LSUIElement` accessory apps using a non-activating `NSPanel`; pywebview creates a
plain `NSWindow`, and making Lodestone dockless is not a trade worth this.

**This is why the in-app row in the Models panel stays on screen either way.**

### 3. Showing the card stole keyboard focus from the browser

pywebview's `show()` is `makeKeyAndOrderFront_` followed by
`activateIgnoringOtherApps_(YES)` — it yanks focus out of the browser the user is
signing in to, on **every** card update. Replaced with `orderFrontRegardless()`.
Clicking the card still brings the app forward normally.

**Verified:** `NSApp.isActive` stays `False` after the initial raise, after the
user clicks back into the other app, and after the in-place success update.

### 4. The card tore itself down the instant the browser opened

**Symptom:** "the cancel button is appearing but it got disappear as soon as the
browser window got open."

**Cause:** in `app.js`, `if (!floating) toast(...)` sat one statement **above**
`const floating = await raiseFloatingSigninCard(...)`. Reading it threw a
temporal-dead-zone `ReferenceError`, which the handler's own `catch` turned into
"Sign in error" and `stopPolling()` — tearing down the cancel row. The floating
card was never raised at all, because the throw happened before the call.

**Why nothing caught it:** `node --check` passes on TDZ. The click harness existed
and clicked the button, but every fixture short-circuited into the CLI branch, so
the browser branch never ran. And the error text was wiped by the re-render that
followed it, so asserting on the final DOM saw a clean screen.

**Now:** the harness is driven with an explicit browser-flow response, stubs the
pywebview bridge, and records every `textContent` write.

### 5. Every other launch opened an empty app

**Symptom:** "first time nothing is showing, then I quit and relaunch, then the
app starts."

**Cause:** `_stable_port` probed the saved port by binding **without**
`SO_REUSEADDR`. After a quit that port still holds connections in `TIME_WAIT`, so
the probe called it taken — on a port uvicorn would have bound fine. The app fell
back to a **random port**, and because `localStorage` is keyed to the origin, the
onboarding flag, the chosen model and the lead agent vanished with it. One more
quit let `TIME_WAIT` expire and the state came back.

**The webview origin is user state.** The port is not an implementation detail.

**Fix:** bind the way uvicorn does and hand the bound socket straight to the
server, closing the gap between checking a port and serving on it.

### 6. 158 live `claude auth login` processes

**Symptom:** the app lagged, froze, needed force-quitting; sign-in stopped working.

**Cause, in two parts:**
- Nothing reaped a vendor CLI's `login`. It waits for a browser callback that may
  never come, and the only handle lived in module state, so every launch forgot
  the previous launch's.
- **The test suite spawned one on every run.** `flow.start()` and
  `POST /signin` reach the real binary. Reproduced: 0 → 1 per `pytest` run,
  bisected to `test_model_layer_freeze.py` and `test_native_accounts.py`. Given
  how often the suite runs, that was the dominant source — my first attribution
  ("every sign-in you ever started") was wrong.

**Fix:** `login_processes.py` records each spawned login **to disk**, because the
process that has to clean up is not the one that made the mess. `run_app` reaps on
launch and on quit. Only recorded PIDs are signalled, and each is re-checked
against the command line first — a reused PID killed is worse than the leak.
`conftest.py` swaps the argv of any `login` spawn for a command that exits
immediately, so flows still run their own code with the vendor binary kept out.

This is the **third** test-hygiene incident here; the others wrote to the real
Keychain and bound the fixed OAuth port 1455.

### 7. A white block under the card

**Symptom:** the dark card, then a white rectangle filling the rest of the window.

**Not the window** — that was already transparent (`isOpaque == False`,
`backgroundColor` alpha `0.0`). It was **WKWebView's `underPageBackgroundColor`**,
opaque white by default, measured at alpha `1.00`. pywebview's transparency
support predates that property and only clears the older `drawsBackground`, which
was already off.

**Fix:** clear it on every raise, since the page reloads for each sign-in.

### 8. A hole between the text and the button

`.action` carried `margin-top: auto`, so it was pushed to the bottom of a
**fixed-height** window and every unused pixel opened as a gap. Now a fixed 14px
gap, the card is exactly as tall as its content, and the window resizes to match
(`_Bridge.fit` → `_resize_now`), keeping its **top edge** — Cocoa's origin is the
bottom-left, so resizing naively walks the card up the screen.

Two traps inside that fix:
- A `ResizeObserver` drives it, not a `fit()` call at each site that rewrites the
  copy: one missed call leaves the card clipped.
- The first measurement lands **before the system font is ready** and comes out
  3px short — enough to cut the cancel link. It re-measures on
  `document.fonts.ready`.

### 9. The window chased a height that kept moving

A window even a pixel shorter than the card grew a **scrollbar**, which narrowed
the body, rewrapped the text and made the card *taller*. `overflow: hidden` on
`html, body` closes the loop. It is load-bearing, not cosmetic.

### 10. Opening the Models drawer froze the app for ~10s

`/api/providers` and `/api/models/catalog` are both fetched every time the drawer
opens, and both shelled out to vendor CLIs and probed local daemons. **Profiled**
(after guessing wrong twice — SQLite and the window layer both looked guilty and
neither was): ~50 Keychain reads each spawning `security`,
`detect_all_accounts()` at 2.41s, `agent --list-models` at 3.11s.

`models/cache.py::ttl_cached` memoises the expensive probes;
`clear_provider_cache()` flushes on any credential change. **5.64s → 0.29s.**

Related: `/auth/status` is polled every 2s during sign-in. Calling the expensive
`/refresh` each tick queued requests faster than the server could finish them and
saturated FastAPI's sync threadpool, freezing the whole app. Poll the cheap
endpoint; call the expensive one **once**, on success.

---

## Current numbers

- Window **348 × 250** initial, fitting to **~219** for the usual case
  (was 420 × 290). Clamped to 150–420.
- Timeout **180s** (`SIGNIN_TIMEOUT_SECONDS`) — deliberately generous; an account
  switch with a password and 2FA blew past 150s in practice.
- Card and window agree exactly, and keep agreeing as the copy changes:
  219/219 → 237/237 → 201/201.
- Layout symmetric: every block inset 17–18px both sides, cancel link centred.

---

## How to debug this again

Screenshots are unreliable here — `screencapture -l` fails when the window is on
another Space. What worked instead:

- **Read the NSWindow directly.** `BrowserView.instances[win.uid].window`, then
  `isVisible()`, `level()`, `collectionBehavior()`, `isOnActiveSpace()`,
  `hidesOnDeactivate()`. `hud.diagnostics()` exposes the cheap parts at runtime.
- **Ask the window server who is on top.** `CGWindowListCopyWindowInfo` returns
  windows front-to-back with `kCGWindowLayer` — the level each window *actually*
  has. That is how "Arc is above us" turned out to be a full-screen menu-bar
  overlay, and how "nothing is above us" was confirmed.
- **Measure the page, don't eyeball it.** `evaluate_js` with
  `getBoundingClientRect` on each element proves alignment numerically, and
  `scrollHeight - clientHeight` proves nothing is clipped.
- **Drive it from a probe that replicates `run_app` exactly**, including
  `private_mode` and the real `_AppBridge` — a simplified probe passed while the
  real app failed.
- **Reintroduce the bug before trusting the test.** Every regression test here
  was checked by putting the old behaviour back and watching it fail.

`GET /api/hud/diagnostics` reports whether the native window exists, the last few
sign-in steps, and any stray login processes. `POST /api/hud/note` is how the page
records which branch it took — four of the five sign-in outcomes never reach the
floating card at all (already connected, CLI required, no browser sign-in), and
they all legitimately render in-app, which is indistinguishable from the card
failing unless someone writes it down.
