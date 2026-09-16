# Model availability, in full

> The short version is in [`/CLAUDE.md`](../../CLAUDE.md) and
> [`chitragupta/models/CLAUDE.md`](../../chitragupta/models/CLAUDE.md). This is the
> whole rule, with the per-provider detail behind it.
>
> One sentence governs everything below: **what a user can run is resolved from
> their own account, never from a table we shipped.**

---

## 1. Authority order

`entitlements.evaluate_model_entitlement` — first answer wins:

1. **Connection.** Provider not connected → everything locked, `"Connect in Models"`.
2. **The provider's own answer** (`provider_reported=`): what *this account* says
   it can run — a live `/v1/models` query made with the user's credential,
   `~/.codex/models_cache.json` (ChatGPT plan), `~/.claude.json`
   `additionalModelOptionsCache` (Claude CLI), the installed Ollama tags.
   **This is the truth and the tables below never override it.**
3. **Static tier tables** (`_MODEL_TIER_REQUIREMENTS`) — a conservative guess
   used ONLY when step 2 has nothing to say: not connected, or discovery failed
   and a hardcoded fallback row is being shown.

So two users on different plans see different selectable models from the same
build. A ChatGPT Free account gets its slugs selectable and the Pro ones greyed
with a reason; a Pro account gets the opposite. **Locked models stay visible**
with a `plan_required` reason — never hidden.

## 2. Hardcoded model lists are fallbacks, not truth

`registry.MODEL_CATALOG`, `discovery._fallback_*()` and
`app.js::FALLBACK_CATALOG` exist only to render something before a credential
exists. Everything they produce is flagged `is_fallback=True` — which is
precisely what tells step 2 it has no provider answer. The moment a credential
is present, live discovery replaces them.

- **Never add a model id to a fallback list without verifying it resolves.**
  Retired ids are worse than a short list: they render as selectable and then
  fail at send time. *(Audited 2026-09-12: 4 of 6 Claude ids, all 5 xAI ids, and
  the OpenRouter and Cursor defaults were dead.)*
- `app.js::FALLBACK_CATALOG` is **generated** from `registry.MODEL_CATALOG` —
  regenerate it rather than hand-editing, so the two cannot drift.
- Never read another product's files — a competitor's app-support directory — to
  discover models or credentials.

## 3. A stored model id is a request, not a guarantee

Model choices persist (an agent binding in `agent_model_configs`,
`chitragupta_model` in localStorage) while provider catalogs move underneath them.
`entitlements.resolve_usable_model()` re-checks every request against what the
account offers *now* and substitutes the best model the user can run.
`run_turn` calls it on the way to `get_provider`, and repairs the agent's saved
binding when that binding was the stale one.

A discovery failure never blocks a turn — the request is honoured. **Never send
an id straight from storage to a provider.**

## 4. Detection is not consent

Finding a CLI, a config file or a session on the machine means we may *offer* it
(`detected_account.found_on_computer` → a "Continue" button). It never means
connected: **no code path may promote a credential to CONNECTED, or treat a
provider as `ready`, because a binary happens to be installed.**

## 5. Credentials are independent

A provider's account and its API key connect and disconnect separately
(`ProviderConnection.account_status` / `api_key_status`,
`set_credential(kind, status)`; `connection_status` is a derived rollup).
Removing a key must never sign the user out, and connecting an account must
never claim a key exists. `/api/providers/{name}/disconnect` takes
`scope=account|api_key|all`.

## 6. We install the vendor CLIs ourselves

`models/cli_manager.py`. Artifacts are fetched **directly** — a vendor's install
script is read as a *manifest* (it names a version and a plain artifact URL) and
never piped into a shell, so the install is auditable, lands in our own
directory, and cannot run arbitrary code as the user.

Downloads run as a background job with progress. A verify step (`--version`)
must pass before the binary is linked, and a failed download is never linked.
`find_*_cli()` prefers our pinned copy over anything on PATH. Managed today:
`cursor` (agent), `grok`. Adding one means adding a `CliSpec` and a resolver.

Finding the binary at all goes through `cli_login.augmented_path()` — a process
launched from Finder inherits a stripped PATH, so a CLI the user definitely
installed is otherwise simply not found.

## 7. A CLI sign-in finishes on its own schedule

The browser flow completes long after any poll window, so:

- the waiting HUD polls `/auth/status` for **every** provider, never a hardcoded
  id list;
- it waits ~10 minutes, and on timeout says what to do instead of vanishing;
- **Refresh re-runs the flow's `status()`**, which adopts a completed sign-in.
  Refresh must be able to *finish* a sign-in, not just re-read state.

**A re-sign-in is not the old session.** Completion is the CLI's login *process
exiting* (or the account visibly changing), never "the account looks
authenticated" — which is already true when switching accounts, and reported
success on the first poll before the user had touched the browser. The shared
`CliLoginSession` in `models/cli_login.py` records who was signed in at start
and compares. `AuthStatus`: **idle** = nothing in flight, **waiting** = a sign-in
we started is running, **success** = it finished.

## 8. A signed-in CLI is the identity

Vendors also cache an account elsewhere — the Cursor *app* keeps a different
email in its sqlite — but the CLI is what we actually run, so its `status`
output wins. Read it from the shape the CLI actually prints (`agent status
--format json` nests identity under `userInfo`).

## 9. Vendor CLIs own sign-in too, not just inference

Each ships a `login` command that opens the vendor's own consent page, because
the OAuth client belongs to that CLI — `agent login` → authenticator.cursor.sh,
`grok login --oauth` → accounts.x.ai ("Authorise Grok Build"), `claude auth
login` → claude.com.

So a "Sign in with X" button spawns `X login` detached and polls a status
command, marking the account connected on success. That is the whole trick
behind competing apps' browser sign-in — no private client ids, no bundled
secrets. The mechanism lives once, in `models/cli_login.py`.

## 10. Every subscription path is a vendor CLI

None of these providers exposes a subscription inference endpoint; each ships an
official headless CLI instead, and that is how a paid plan is reached:

| provider | CLI | headless invocation |
|---|---|---|
| Claude | `claude` | `claude -p --output-format json --model <id>` |
| Cursor | `agent` | `agent -p "<prompt>" --output-format json --model <id>` |
| xAI | `grok` | `grok -p "<prompt>" --output-format json -m <id>` |
| ChatGPT | `codex` | (we use the Codex responses endpoint directly) |

"Support provider X's subscription" almost always means "shell out to X's CLI".
**Check for an official CLI first.**

## 11. A subscription is not an API key

- **Claude** — no subscription inference endpoint, so an account-connected
  Claude with no key is delegated to the local Claude CLI
  (`AnthropicProvider._subscription_backend`).
- **ChatGPT** — no key → the Codex responses path.
- **Cursor** — has **no chat-completions API**. `api.cursor.com` is the
  admin/agent surface (`GET /v1/models` → 401 "Invalid User API Key"), but
  `POST /v1/chat/completions` → **404 Route not found**. Models run through the
  headless CLI. `CURSOR_API_KEY` authenticates *that CLI* via env — it is not a
  REST credential, so a key alone cannot run anything. `find_cursor_cli()`
  verifies the binary really is Cursor's: `agent` is a generic name and a bare
  PATH hit is not trusted.
- **xAI** — a SuperGrok subscription covers grok.com and the mobile apps, and
  grants **no** credits on `api.x.ai`, which is the separately-billed developer
  API. An OAuth sign-in authenticates and then fails every request (including
  `GET /v1/models`) with 402 `personal-team-blocked:spending-limit`. So the OAuth
  token is NOT used as an API key: `XAIProvider._oauth_only` reports not ready
  with an explanation instead. Today xAI is `api_key_only` and needs an
  `XAI_API_KEY` from console.x.ai; the subscription path is the Grok Build CLI.

**Never send a subscription request to an API-key endpoint, and never let a
credential that merely *authenticates* be reported as ready.**

## 12. A provider with no interactive sign-in is derived, never listed

`ProviderCapabilities.api_key_only` (no oauth/browser/device/CLI login) drives
both `/api/providers/{name}/signin` and whether the UI renders account and
sign-in cards. Don't reintroduce `providerId === "gemini"`-style checks in
`app.js` — add the capability and every surface follows.

## 13. One sign-in protocol

`models/auth_flows.py` is the single seam for every provider sign-in.
`get_flow(provider)` returns an `AuthFlow` with `start() -> AuthStart` and
`status() -> AuthStatus`, plus optional `submit_code` / `cancel`.

Routes: `POST /api/providers/{name}/auth/start`, `GET …/auth/status`,
`POST …/auth/code`, `POST …/auth/cancel`. The old per-provider routes
(`/signin`, `/{provider}/oauth-status`, `/claude/submit-code`) are thin aliases.

Which flow a provider gets is derived from its capabilities — `api_key_only` →
`ApiKeyOnlyFlow`, CLI-owned sign-in → its own flow, otherwise `BrowserFlow`.
**Adding a provider means registering a flow, never adding a route or a UI
branch.** A flow must always return a reason rather than raise.

## 14. Provider errors are translated, never dumped

`models/errors.py` holds one taxonomy for every backend — `ErrorKind` (auth ·
billing · rate_limit · model_not_found · model_not_entitled · context_too_long ·
content_filtered · bad_request · server · network · timeout) and a
`ProviderError` carrying an actionable message, a redacted detail, and
`retryable`.

- Classify at the boundary: `classify_http(provider, status, body, model=,
  key_env=)` for HTTP, `classify_exception(...)` for transport failures,
  `classify_cli(...)` for CLI-backed providers. Return `err.as_reply()`.
- **Status alone is not enough** — a 400 can be a bad model, an over-long
  context, a content filter or a billing block, so the body is inspected first.
- **Never surface raw provider JSON**, and never a credential: `redact()` strips
  `sk-…`, `xai-…`, `AIza…` and bearer tokens from anything user-visible.
- Messages name the provider's `display_name`, never its internal id.
- A model-level failure suggests models this user can actually run (via the live
  catalog, locked ones excluded).
- Providers sharpen a classified error by overriding `_refine_error(err)` — that
  is how xAI explains the subscription/API-credit split rather than saying a
  generic "out of credits".
- **A `chat()` must return a `ChatResult`, never raise.** An uncaught
  `raise_for_status()` is what turned a Claude 401 into a 500.

## 15. Streaming

Two wire formats cover everything (`models/streaming.py`): Anthropic Messages
(Claude API + Claude CLI's `stream_event` nesting + Grok CLI) and OpenAI
chat-completions (OpenAI, OpenRouter, Ollama, DeepSeek, xAI, Gemini).

`LLMProvider.stream()` defaults to yielding a whole `chat()` in one piece, so no
caller ever branches on whether a backend can stream. CLI backends fall back
when a stream yields no text — decided *before* emitting anything, since falling
back afterwards would duplicate it.

**In the browser, reassemble SSE frames across chunk boundaries**: one network
chunk is not one frame, and a reader that assumes it passes every hand test and
drops tokens for real.

## 16. The Models drawer is executed in tests, not parsed

Two node harnesses under `tests/js/`, driven by `tests/test_models_drawer_render.py`:

- `render_provider_box.mjs` runs `renderProviderConnectBox` against a real
  `/api/models/catalog` payload and checks each provider's cards.
- `click_signin.mjs` runs the actual **click handler** and checks what lands on
  screen. Its DOM stub deliberately models detachment — reassigning `innerHTML`
  clears the subtree — because the bug it exists to catch was a card written
  into a container a preceding re-render had already replaced.

Two ways these go blind, both learned the hard way:

- **Clicking is not covering.** `click_signin.mjs` existed and clicked the
  button, but every fixture short-circuited into the CLI branch — so the browser
  branch, where a second TDZ read of `floating` lived, never ran. Feed the
  harness an **explicit** `authStartResponse` per branch (see `BROWSER_FLOW`)
  instead of whatever `get_flow().start()` happens to return on this machine.
- **Read the write, not the aftermath.** A handler's own `catch` calls
  `stopPolling()`, which re-renders the box and wipes the error it just set, so
  asserting on the final DOM sees a clean screen. The stub records every
  `textContent` write (`textWrites`); assert against that.

Neither `node --check` nor source-order assertions catch these: a temporal
dead-zone `ReferenceError` blanked the whole drawer and still passed
`node --check`, and the detached-container bug passed a source-order test.

## 17. Derive UI from capabilities, never from a provider-id chain

Which cards a provider gets comes from `api_key_only` /
`has_interactive_signin`; badge text comes from `isFoundOnComputer`; brand copy
falls back to the provider's label. Every `providerId === "x"` branch in a
render path is a latent bug for the provider that isn't in the chain — that is
exactly how `claude-code` ended up badged "Using this account" while it was only
detected on the machine.
