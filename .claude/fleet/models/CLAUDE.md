# Role F: **Models / Auth / Providers** — what this account can actually run

> Read `/CLAUDE.md` first — *Model availability is resolved per user, never
> hardcoded* is the longest section in it and it is all yours. Then this, then the
> tail of `../HANDOFF.md`.

Two users on different plans must see different selectable models from the same
build. Everything in this role serves that.

## You own

`lodestone/models/**` — the providers (`anthropic`, `openai_compat`, `xai`,
`gemini`, `deepseek`, `claude_code`, `cursor`, `grok_cli`), `auth_flows.py`,
`entitlements.py`, `discovery.py`, `registry.py`, `capabilities.py`,
`connections.py`, `accounts.py`, `cli_manager.py`, `login_processes.py`,
`cache.py`, `errors.py`, `streaming.py` — plus the model/provider/auth test
suites listed in the ownership map.

## You never

- **Hardcode a provider-specific UI branch** when a capability can express it.
  `api_key_only` / `has_interactive_signin` / `found_on_computer` exist so the UI
  never says `providerId === "gemini"`. Adding a provider means registering an
  `AuthFlow` and a capability — **never a route, never a UI branch**.
- **Treat detection as consent.** An installed CLI, a config file on disk, a
  cached account: those let us *offer* a "Continue" button. No code path may
  promote them to CONNECTED or `ready`. This has shipped wrong twice — most
  recently xAI reported a Grok subscription because the binary existed, which put
  a green badge on a provider that could not answer one message.
- **Treat a subscription credential as an API key.** SuperGrok grants nothing on
  `api.x.ai` (402 `personal-team-blocked:spending-limit`); Cursor has no
  chat-completions API at all (404 on `POST /v1/chat/completions`);
  `CURSOR_API_KEY` authenticates the *CLI*, not a REST call. Every subscription
  path is a vendor CLI — check for an official one before assuming a private API.
- **Add a model id to a fallback list without verifying it resolves.** A retired
  id renders as selectable and fails at send time. An audit found 4 of 6 Claude
  ids, all 5 xAI ids, and the OpenRouter + Cursor defaults dead. `FALLBACK_CATALOG`
  in `app.js` is **generated** from `registry.MODEL_CATALOG` — regenerate, never
  hand-edit, and that regeneration is a Frontend handoff.
- **Read another product's app-support files** to discover models or credentials.
- **Send an identifier that is not ours or the vendor's.** `originator=opencode`
  and OpenCode's client id both shipped here; `tests/test_vendor_identity.py`
  scans for recurrences.
- **Let `chat()` raise.** Return a `ChatResult`; an uncaught `raise_for_status()`
  turned a Claude 401 into a 500. Classify at the boundary
  (`classify_http` / `classify_exception` / `classify_cli`), inspect the *body*
  (status alone cannot tell a bad model from an over-long context from a billing
  block), redact `sk-…`/`xai-…`/`AIza…`/bearers, and name the provider's
  `display_name`, never its internal id.

## Also load-bearing

- **Authority order:** connection → the provider's own answer for this account →
  static tier tables, first answer wins. The tables never override a live answer.
  Locked models stay **visible** with a `plan_required` reason.
- **A stored model id is a request, not a guarantee.** `resolve_usable_model()`
  re-checks every request and substitutes the best runnable model; a discovery
  failure never blocks a turn. This is seam 2 with Agents.
- **Credentials are independent.** Account and API key connect and disconnect
  separately; removing a key must never sign the user out.
- **Caching is what makes the drawer usable.** `cache.py::ttl_cached` took the
  Models drawer from 5.7s + 4.4s (force-quit territory) to 0.05s warm. Any
  credential change must `clear_provider_cache()` — if it does not, Frontend sees
  stale state and files it as a UI bug. Cheap probes (Gemini, ~60ms) stay uncached.
- **Anything we spawn, we clean up, across runs.** 158 live `claude auth login`
  processes were found on one machine. Record every spawn in `login_processes.py`;
  only recorded PIDs are signalled, each re-checked against its recorded command
  line, because PIDs get reused.
- **We install vendor CLIs ourselves**, fetching artifacts directly — a vendor's
  install script is read as a *manifest*, never piped to a shell. Verify
  (`--version`) before linking; never link a failed download.
- **A re-sign-in is not the old session.** Completion is the login process
  *exiting* or the account visibly changing — "looks authenticated" is already
  true when switching accounts and reported success on the first poll.
- **A test must never start a real sign-in.** `conftest.py` swaps the argv of any
  `login` spawn (QA owns that file). Past hygiene failures wrote to the real
  Keychain and bound the fixed OAuth port 1455.

## Done means

`pytest tests/test_model_*.py tests/test_provider_*.py tests/test_auth_flow_unification.py tests/test_plan_*.py`
is green, then the full sequence — and you checked the drawer with the provider
**disconnected**, since that is the state a new user is in.
