# `chitragupta/connectors/` — the sources

One class per source, registered in `__init__.py::REGISTRY`.

- Sync idempotently, redact secrets on ingest, survive a crash without taking the
  whole sync down, and stay cancellable.
- Hand-written connectors are read-only by design. `mcp_source.py` is the one
  path that changes something at a vendor, and `perform()`'s `confirmed` gate is
  required rather than defaulted, so a caller that forgets it fails closed.
- **A tool is a write unless it proves otherwise.** `_is_write()` needs evidence
  to call something a read — the server's own `readOnlyHint`, or a recognised
  read verb. It ran the other way once, and handed `merge_pull_request` to a
  model as a tool it could call unattended.
- **A server is local or remote, and remote is not a broker.** `transport="http"`
  reaches the vendor's own endpoint with the user's own credential; nothing sits
  in between, and no third-party code runs as the user. OAuth uses Dynamic
  Client Registration, so we still register no OAuth client.
- **Nothing secret goes in `mcp_servers.json`.** That file is returned verbatim
  by `GET /api/connectors`. Values live in the Keychain under
  `secret_key(server_id, var)`; the spec carries names only.
- **A probe never opens a browser.** `auth_provider(..., interactive=False)` is
  the default because the Connectors page probes on load and the scheduler syncs
  on a timer. Only an explicit Connect may take over the user's screen.
- `converse()` bounds the whole exchange, not just the reply — a server that
  hangs while starting never reaches a call, and one wedged server otherwise
  holds a slot in the six-wide probe lane forever.
- `mcp_tools.py` exposes a server's **read** tools to the agent loop and
  `write_tools()` the proposable ones. Listing starts every server, so it is
  TTL-cached; results are bounded and say so.
- Never read another product's app-support directory for credentials or models.

Rules: [`/CLAUDE.md`](../../CLAUDE.md) · [`docs/CONNECTORS.md`](../../docs/CONNECTORS.md)
· contract: [`docs/development/mcp-contract.md`](../../docs/development/mcp-contract.md).
