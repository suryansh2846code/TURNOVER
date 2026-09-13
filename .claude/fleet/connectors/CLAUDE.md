# Role G: **Connectors** — how the user's real work gets in

> Read `/CLAUDE.md` first, then `docs/CONNECTORS.md`, then this, then
> `../HANDOFF.md`.

One class per source, registered in `connectors/__init__.py::REGISTRY`. Read-only
by default, lazy-imported SDKs, and graceful when unconfigured — because the app
must open and explain itself with nothing connected.

## You own

`lodestone/connectors/**` — `gmail`, `gcal`, `gdrive`, `google_auth`, `notion`,
`github`, `linear`, `files`, `notes`, `apple_mail`, `apple_calendar`, `imessage`,
`custom_api`, `mcp_source`, `mcp_catalog`, `mcp_errors`, `base` — plus
`lodestone/mcp_server/**` (the server we expose), `docs/CONNECTORS.md`, and
`tests/connectors/**`.

## You never

- **Hardcode Brain graph logic around a connector name.** Enrichment is
  content-based and general; a name check here is a bug for every connector
  written after it, including the user's own custom one.
- **Let one bad item abort a sync.** Crash isolation is a shipped property (H2):
  per-item failure, recorded through `suppressed("…")`, sync continues.
- **Break cancellation.** `sync_all` is cooperative-cancelable
  (`POST /api/sync/cancel`) and onboarding depends on it — Build must never block
  on a full first sync.
- **Mix credentials between sources.** Google's three connectors share one OAuth
  by design (C3); everything else is isolated. Secrets go through
  `settings.set_secret`/`get_secret` (Keychain-backed), never into code, never
  into a log.
- **Claim a source is connected because a client id is bundled.** Google shows as
  *disconnected* until real sign-in — `/api/google/status` deliberately overrides
  the bundled-client `ready`. That is the same rule as "detection is not consent",
  in your layer.

## Load-bearing details

- **Ingestion contract:** stable source id, source attribution on every memory,
  real timestamps (not ingest time), HTML stripped, idempotent re-sync. The suites
  in `tests/connectors/` check exactly this — contract, idempotency, crash
  isolation, redaction, sync fixtures.
- **Redact on ingest, before anything else sees the text.** Brain masks secrets
  before extraction, but the first place a token appears is here.
- **Bounded by default:** Gmail 600/90d, Drive 500, Files 2000. **The uncapped
  ones are the real scaling risk** — iMessage has no cap, and recall is linear in
  memory count (`docs/SCALING.md`). Adding a source means deciding its bound.
- **Drive is lazily fetched** (A12) and Gmail paginates all mail with real dates
  (C4) — both were decisions with a recorded reason; read `docs/DECISIONS.md`
  before "simplifying" either.
- **MCP is the biggest multiplier left.** The client side (`mcp_source.py`,
  `mcp_catalog.py`) is the mirror of the server we already ship and is
  `docs/ROADMAP.md` item 1, in progress separately — check for an active session
  before starting on it.
- **Full Disk Access is a product problem, not a permission problem.** iMessage and
  Apple Mail need it, no prompt can request it, and without an explanation the app
  simply looks broken on someone else's Mac (`ROADMAP` item 2). Your half is
  reporting the capability honestly; the explainer is Frontend's, the entitlement
  is Desktop's.

## Done means

`pytest tests/connectors` green, then the full sequence — and you ran a real sync
for the source you touched, then confirmed the memories carry the right source and
real dates, and that cancelling mid-sync leaves the brain consistent.
