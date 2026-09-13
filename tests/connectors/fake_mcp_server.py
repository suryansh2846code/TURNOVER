"""A real MCP server, run as a real subprocess by the tests.

Stubbing the protocol would test the stub. The whole risk in Phase 2 is the
handshake, the transport and the shapes a server actually answers with, so the
tests spawn this over stdio exactly as the connector will spawn a vendor's.

Behaviour is chosen by argv so one file can stand for the several kinds of
server that exist in the wild:

    listing   — a bulk tool taking no arguments (the case that can seed a brain)
    search    — only a tool requiring `query` (search-only; must NOT be synced)
    text      — returns a JSON document inside a text block, not structured
    prose     — returns plain text, no JSON at all
    writes    — carries a destructive tool, which a sync must never call
    huge      — answers with far more text than a context window can hold
    stall     — starts but never finishes the handshake
    crash     — exits during startup
    hang      — never answers
"""
from __future__ import annotations

import sys
import time

from mcp.server.mcpserver import MCPServer

MODE = sys.argv[1] if len(sys.argv) > 1 else "listing"

if MODE == "stall":
    # Before any protocol at all, so the *handshake* is what hangs — the
    # case a per-call timeout can never reach.
    time.sleep(600)

if MODE == "crash":
    sys.stderr.write("fatal: could not open the vendor database\n")
    raise SystemExit(3)

mcp = MCPServer("fake-source")

RECORDS = [
    {"id": "1", "title": "Quarterly planning", "body": "Ship the connector layer."},
    {"id": "2", "title": "Launch checklist", "body": "Notarise the build first."},
    {"id": "3", "title": "Hiring loop", "body": "Two interviews scheduled Friday."},
]


if MODE in ("listing", "writes"):
    @mcp.tool()
    def list_records() -> list[dict]:
        """Every record this source holds."""
        return RECORDS

if MODE == "writes":
    @mcp.tool()
    def delete_record(record_id: str) -> str:
        """Permanently remove a record. A sync must never reach this."""
        return f"deleted {record_id}"

    @mcp.tool()
    def send_message(to: str, body: str) -> str:
        """Send a message to someone."""
        return f"sent to {to}"

if MODE == "search":
    @mcp.tool()
    def search_records(query: str) -> list[dict]:
        """Find records matching a query. Cannot enumerate."""
        return [r for r in RECORDS if query.lower() in r["title"].lower()]

if MODE == "text":
    @mcp.tool()
    def list_entries() -> str:
        """Records as a JSON document inside a text block."""
        import json
        return json.dumps({"items": RECORDS})

if MODE == "prose":
    @mcp.tool()
    def list_notes() -> str:
        """Records as plain prose, which is still worth keeping."""
        return ("Quarterly planning: ship the connector layer.\n"
                "Launch checklist: notarise the build first.")

if MODE == "huge":
    @mcp.tool()
    def read_everything() -> str:
        """Answers with megabytes, the way a raw-JSON vendor tool does."""
        return "x" * 200_000


if MODE == "hang":
    @mcp.tool()
    def list_records() -> list[dict]:
        """Never answers, so the timeout path is exercised for real."""
        time.sleep(600)
        return RECORDS


if __name__ == "__main__":
    mcp.run()
