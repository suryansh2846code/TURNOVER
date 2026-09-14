# Frontend testing — how it works, and what it constrains

> **Why this file exists:** the single most important fact about `app.js` is not
> in the code and was not written down anywhere — *the test harnesses can only
> load it as one whole file.* That is what makes splitting it a test-architecture
> change rather than a code change. Read this before touching `lodestone/web/`.

---

## 1. Current architecture

There is no browser, no jsdom, no test framework on the frontend side. Each
harness is a plain Node script that **fabricates just enough of a browser**,
evaluates `app.js` inside it, calls one function, and prints JSON. A pytest
driver runs the script and asserts on that JSON.

```
tests/test_models_drawer_render.py          pytest driver
        │  subprocess.run(["node", harness, APP_JS], input=<json fixture>)
        ▼
tests/js/render_provider_box.mjs            the harness
        │  fs.readFileSync(APP_JS)
        │  new Function(src + "globalThis.__render = renderProviderConnectBox;")()
        ▼
lodestone/web/app.js                        evaluated as ONE script body
        │  writes into the stub DOM
        ▼
   JSON on stdout  ──────────────────────►  assertions in the driver
```

### 1.1 The ten harnesses

| harness | pulled out of the closure | driven by |
|---|---|---|
| `render_provider_box.mjs` | `renderProviderConnectBox` | `test_models_drawer_render.py` |
| `click_signin.mjs` | `renderProviderConnectBox` (then clicks it) | `test_models_drawer_render.py` |
| `model_selection.mjs` | `setActiveModel`, `renderProviderFlyout` | `test_model_selection_is_honest.py` |
| `connector_catalog.mjs` | `connectorBrowser`, `loadConnectorCatalog`, `connectorPermissions`, `loadApprovals` | `test_connector_catalog_ui.py` |
| `tool_provenance.mjs` | `renderToolList` | `test_frontend_tool_provenance.py`, `test_contract_tool_rows.py` |
| `tool_result_injection.mjs` | `addMsg`, `addTrace`, `parseActions` | `test_frontend_tool_result_injection.py` |
| `action_card.mjs` | `parseActions`, `actionCard`, `md` | `test_frontend_injection.py`, `test_frontend_tool_result_injection.py` |
| `stream_turn.mjs` | `streamTurn` | `test_frontend_streaming.py` |
| `a11y_keyboard.mjs` | `loadAgents` | `test_frontend_keyboard_access.py` |
| `signin_hud.mjs` | *(none — see 1.5)* | `test_signin_hud.py`, `test_signin_hud_window.py` |

### 1.2 How a function is reached

`app.js` is a classic script: every declaration is a local of the script body,
not a property of anything. A harness therefore appends an export epilogue to
the source string before evaluating it:

```js
new Function(
  src +
  "\nglobalThis.__render = renderProviderConnectBox;" +
  "\nglobalThis.__setCatalog = (c) => { MODEL_CATALOG = c; };"
)();
```

The second line matters as much as the first: some harnesses have to **write** a
module-level `let` (`MODEL_CATALOG`, `COMPOSER_PROVIDERS`) to install a fixture.
Only a closure that is inside the same script body can do that, which is exactly
why the epilogue is concatenated rather than imported.

### 1.3 Browser globals each harness stubs

Union across all ten: `document`, `window`, `fetch`, `localStorage`,
`sessionStorage`, `MutationObserver`, `setTimeout`, `setInterval`,
`clearInterval`, `requestAnimationFrame`, `cancelAnimationFrame`,
`AbortController`, `TextDecoder`, `URLSearchParams`, `ResizeObserver`,
`confirm`, `prompt`, `location`.

`MutationObserver` is required by **every** harness, not because the test needs
it, but because `app.js` installs a focus-management observer at load — without
the stub the whole script throws before the function under test is reached.

### 1.4 Two DOM assumptions that are the point, not an accident

- **Reassigning `innerHTML` detaches the subtree.** The stub clears `_kids` on
  every `innerHTML` write, because the bug `click_signin.mjs` exists to catch
  was a card written into a container that a preceding re-render had already
  replaced. A stub that kept returning the same child would pass.
- **Reading the final DOM is not enough.** A handler's own `catch` calls
  `stopPolling()`, which re-renders and wipes the error it just set, so the end
  state looks clean. The stub records **every** `textContent` write into
  `textWrites`, and assertions read that.

### 1.5 `signin_hud.mjs` is not an `app.js` harness

It slices the inline `<script>` out of `lodestone/web/signin_hud.html` and
evaluates that. It shares the technique and none of the constraint, so nothing
in a future `app.js` split affects it.

### 1.6 What the runtime assumes

Node ≥ 18 for `fetch`/`TextDecoder`, `--check` for syntax, and nothing else. No
package.json, no node_modules, no install step — which is a real feature: the
frontend tests run in CI with only `node` present. **Preserve that.**

---

## 2. The problem

```js
new Function(src)        //  ← cannot evaluate `import` or `export`
```

`new Function` compiles a *script*, not a *module*. That single fact means:

1. **`app.js` cannot become an ES module.** Converting it — or splitting it into
   `import`-ing modules — breaks all nine harnesses at once, and with them
   `test_models_drawer_render.py`, `test_model_selection_is_honest.py`,
   `test_connector_catalog_ui.py`, `test_frontend_tool_provenance.py`,
   `test_contract_tool_rows.py`, `test_frontend_tool_result_injection.py`,
   `test_frontend_injection.py`, `test_frontend_streaming.py` and
   `test_frontend_keyboard_access.py`.
2. **Each harness takes exactly one path** (`process.argv[2]`) and reads exactly
   one file. Even a split into plain classic scripts leaves every harness
   loading one twelfth of the app.
3. **The harnesses must be able to write module-level `let`s**, so whatever
   replaces the single file has to keep every piece in one shared scope.

The browser side has no such problem: several `<script src>` tags share one
global scope and execute in document order, which is semantically identical to
today's single file. **The constraint is entirely in the test harness.**

---

## 3. Target architecture

Keep everything that works. Change one thing: *where the harness gets its
source*.

```
lodestone/web/index.html
    <script src="/static/core.js"></script>      ← load order is declared here,
    <script src="/static/providers.js"></script>    once, and nowhere else
    <script src="/static/app.js"></script>
                    │
                    │  same global scope, document order — identical to today
                    ▼
tests/js/_app_source.mjs           NEW — ~20 lines, no dependencies
    parses index.html for <script src="/static/*.js"> in order
    returns the concatenated source
                    │
                    ▼
tests/js/render_provider_box.mjs   one line changes:
    - const src = fs.readFileSync(APP_JS, "utf8");
    + const src = appSource(WEB_DIR);
```

Why derive the order from `index.html` rather than hardcode a list:

- **One source of truth.** The order the browser uses *is* the order the test
  uses. They cannot drift, because there is only one list.
- **Adding a future module touches no harness.** Add the `<script>` tag; every
  harness picks it up.
- **It tests the real contract.** If a module is added to disk but never wired
  into the page, the harness loads what the browser loads: nothing. That is a
  bug the current setup cannot express.

Everything else is unchanged — the stubs, the export epilogue, the JSON
protocol, the pytest drivers, the no-dependency property.

### What is deliberately not proposed

- No jsdom, no vitest, no jest, no package.json. The current harnesses catch
  bugs those tools would not (§1.4) and cost nothing to run.
- No ES modules. §2.
- No change to what any harness asserts.

---

## 4. Migration steps

Each step ends green. The split does not begin until step 3 is proven.

| step | change | files | verification | status |
|---|---|---|---|---|
| **1** | Add `tests/js/_app_source.mjs`. Nothing uses it yet. | 1 new | its output for a single-script `index.html` is byte-identical to `readFileSync(app.js)`, pinned by `tests/test_frontend_source_loader.py` | **done** |
| **2** | Point all nine harnesses at it. **`app.js` is still one file**, so a pure no-op refactor of the loader. | 10 | suite unchanged — 1440 passed, 1458 collected, before and after. Proven real by deleting app.js's `<script>` tag: 26 passing harness tests become 18 failures and 7 errors. | **done** |
| **3** | Prove the mechanism: move **one** small, self-contained cluster out — `core.js` (`$`, `api`, `esc`, `md`, `toast`, orbs, icons) — and add its `<script>` tag **first** in `index.html`. | 7 | suite green **without touching a harness**. Removing core.js's tag, or loading it after app.js, each turn 19 passing drawer tests into 11 failures and 7 errors. | **done** |
| **4** | `providers.js` — the catalog state, the sign-in HUD, the CLI instructions, `renderProviderConnectBox`. | 3 | 70 frontend tests green, no harness touched. app.js 3,507 → 2,645. | **done** |
| **5** | The remaining clusters, one commit each: `models.js` (845), `chat.js` (380), `brain.js` (223), `connectors.js` (302), `workspace.js` (378), `brain-screen.js` (160), `usage.js` (142), `tools.js` (143). | 3 each | suite green between each | **done** |

**The split is complete.** `app.js` went 3,581 → 208 lines across eleven files,
and no harness was touched after step 2.

### A fifth check, learned the expensive way

The `tools.js` cut ended one line early, leaving `loadTools`' closing brace
behind in `app.js`. The two halves **cancelled out** when the files were
concatenated, so `node --check` on the whole was perfectly happy — while every
top-level declaration after the seam sat nested inside a truncated function and
nothing was global any more.

So the checks before a cut are now five, and this is the one people skip:

5. **Does each file parse on its own?** Parsing the concatenation is not the
   same question, and a cut that is off by one brace passes the concatenation
   check while breaking the app at runtime.

### Deciding which cluster goes next

Not by size — **by which way the state points**. `providers.js` went before the
model picker, reversing an earlier guess, because `PROVIDERS` and
`MODEL_CATALOG` are declared in it and read by four things downstream. Taking
the picker first would have left it reading state declared in a file loaded
after it.

Four static checks are worth running before any cut, because a mistake here is a
blank screen rather than a failed assertion:

1. **Which names cross the cut, and in which direction.** A backwards reference
   is only safe if it is called at runtime, never evaluated at load.
2. **Does anything in the region execute at load time?** If not, script order
   cannot produce a temporal dead-zone read.
3. **Any duplicate top-level declaration across files?** `let` is not
   redeclarable in the shared script scope — that is a SyntaxError at load, not
   a test failure.
4. **Does the concatenation still parse as one unit?** That is what the browser
   and every harness actually evaluate.

Step 3 cost more than three files, for a reason worth knowing before step 4:
**two Python tests were reading `app.js` when they meant "the app's
JavaScript".** One greps for `prefers-reduced-motion`; the other extracts every
`(method, path)` the frontend calls. Both now use `tests/web_sources.py`, which
reads `index.html` the same way `_app_source.mjs` does, and a test asserts the
two loaders agree.

**Before moving anything, grep for who reads the file you are moving out of.**
A test that greps one file out of several does not fail — it passes, for the
wrong reason.

Step 2 needed one unplanned fix, worth knowing about before writing another
harness driver: `test_frontend_tool_provenance.py` mutates `app.js` into a temp
directory to prove its harness is not blind. A lone file there has no page to be
loaded by, so it now copies the whole web directory and mutates the copy. Any
future driver that fabricates a source tree has to fabricate an `index.html`
with it.

### The rules that govern steps 3+

- **Load order is the dependency graph.** `core.js` goes first because 119 call
  sites use `esc()`/`md()`. A `const` arrow moved above its first use is a
  temporal-dead-zone `ReferenceError` that `node --check` passes and that blanks
  a screen — it has happened twice here.
- **`_lessMotion` is a hoisted `function` on purpose**, because `_bsDraw` calls
  it from far above. Anything with the same shape must keep it.
- **`md()` escapes before applying inline markup.** `esc(src)` runs first and the
  link regex is safe only because quotes are already `&quot;`. This invariant
  moves with the function, byte-for-byte, or it does not move.
- **No behaviour change in a move commit.** A move commit renames nothing,
  reorders nothing, and fixes nothing.
