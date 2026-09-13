# `lodestone/connectors/` — the sources

One class per source, registered in `__init__.py::REGISTRY`.

- Sync idempotently, redact secrets on ingest, survive a crash without taking the
  whole sync down, and stay cancellable.
- Connectors are read-only by design. `mcp_source.py::MCPConnector.perform()` is
  the one path that changes something at a vendor, and its `confirmed` gate is
  required rather than defaulted, so a caller that forgets it fails closed.
- `mcp_tools.py` exposes a server's **read** tools to the agent loop. Listing
  starts every server, so it is TTL-cached; results are bounded and say so.
- Never read another product's app-support directory for credentials or models.

Rules: [`/CLAUDE.md`](../../CLAUDE.md) · [`docs/CONNECTORS.md`](../../docs/CONNECTORS.md).
