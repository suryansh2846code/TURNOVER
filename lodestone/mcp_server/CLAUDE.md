# `lodestone/mcp_server/` — the MCP server we expose

Lodestone's brain, offered to any MCP client.

The **client** side — consuming someone else's MCP server — is not here: sources
live in `../connectors/mcp_source.py` and the agent-facing read tools in
`../connectors/mcp_tools.py`. Both shipped 2026-09-13.

Rules: [`/CLAUDE.md`](../../CLAUDE.md).
