# The MCP contract — what each layer promises the next

> Written before the code, per `/CLAUDE.md` ("a change that spans two layers").
> This change spans five: `connectors/`, `agents/`, `actions.py`, `api/`, `web/`.
> Every row below is a promise something else depends on.

## Why this landed

The layer was built to the right shape and could not be reached. Zero of four
catalog entries started (two packages deprecated upstream, one absent from npm
entirely, one needing a positional argument the catalog could not express), so
no server could be added; and no agent could ever write to one, because
`parse_actions()` had no `mcp_action` arm and the system prompt never mentioned
it. Reads worked well and had nothing to read from.

## 1. A server spec can be local *or* remote

`MCPServerSpec` gains `transport`, and the rest of the layer stops assuming a
subprocess.

| field | meaning |
|---|---|
| `transport` | `"stdio"` (a local subprocess) or `"http"` (the vendor's own server) |
| `url` | the endpoint, for `http`. Empty for `stdio` |
| `command` / `args` | how to launch, for `stdio`. Empty for `http` |
| `env_keys` | **names** of environment variables this server needs |
| `allowed_tools` | tools this connector may use. Empty = every readable tool |

**`env` is gone from the spec.** Values live in the Keychain under
`mcp:<server_id>:<VAR>`, exactly as `custom_api.py` already stores its token,
and are hydrated at spawn time by `resolved_env()`. `as_dict()` therefore
carries no secret, which is what lets `GET /api/connectors` keep returning it.

Remote servers authenticate with OAuth 2.1 + Dynamic Client Registration, so
**Chitragupta still registers no OAuth client** — the property the stdio path was
chosen for, kept, without running third-party code as the user. Tokens go
through the same Keychain, behind `KeychainTokenStorage`.

**Migration is automatic and one-way:** a spec loaded with a legacy plaintext
`env` moves those values into the Keychain and rewrites itself without them.

## 2. A tool is a write unless it proves otherwise

`classify_tools()` inverts. Previously a tool was a write only if its name hit
one of fourteen stems, so `merge_pull_request`, `execute_sql` and `revoke_token`
were handed to the model as reads. Now:

    read  ⟸  readOnlyHint is True
          ∨  (no required arguments beyond paging ∧ name matches a read stem)
    write ⟸  everything else

The cost is that an unannotated read gets an approval card. That is the correct
direction to be wrong in, and it is the direction `/CLAUDE.md` already requires
of the outbound path.

`ToolKinds` gains `.reason_for(tool)` so the confirmation card can say *why*
something needs approval.

## 3. An agent proposes a connector write the same way it proposes an email

The plumbing existed end to end — `actions.REGISTRY["mcp_action"]`,
`permissions.NEVER_UNATTENDED`, the approvals queue, the API route — and nothing
could originate one. Three additions close it:

- **`actions.parse_actions()`** grows an `mcp_action` arm. The tag's inner text
  is JSON: `<action type="mcp_action" server="linear" tool="create_issue">
  {"title": "..."}</action>`. Attributes are flat strings, and a vendor's tool
  takes an object — so the arguments are the body, parsed with `json.loads` and
  **rejected rather than guessed at** when malformed.
- **`agent.py`** tells the model the tag exists, and lists the write tools its
  connectors actually expose. A model cannot propose what it was never shown.
- **`chat.js`** renders the card. Its `actionCard()` previously fell through to
  "Create calendar event" for any unknown type, so an `mcp_action` would have
  rendered as a calendar entry.

`mcp_action` stays in `NEVER_UNATTENDED`. Nothing about this change lets an
unattended routine write to a connector without a tap.

## 4. What the API promises

| endpoint | promise |
|---|---|
| `GET /api/connectors` | `config` never contains a secret value |
| `POST /api/connectors/mcp` | add a server by hand, verified before saving |
| `PATCH /api/connectors/mcp/{id}` | set `allowed_tools`; calls `invalidate()` |
| `POST /api/connectors/mcp/{id}/auth` | begin a remote server's OAuth consent |
| `GET /api/connectors/mcp/{id}/auth` | poll it — `pending` \| `connected` \| `failed` |
| `POST /api/connectors/catalog/{id}` | accepts `args` as well as `env` |

Every one of these is added to `tests/api_surface.json` in the same commit.

## 5. What the connector layer promises the agent layer

Unchanged on purpose — `MCPToolRef` / `list_tools()` / `call_tool()` /
`invalidate()` keep their shapes, so `agents/mcp_tools.py` needs no edit to
benefit from any of the above. `MCPToolRef.writes` simply becomes trustworthy.

One addition: `write_tools()` returns the proposable writes, because the agent
layer now has to name them in a prompt.

## 6. Timeouts, and where they live

`converse()` bounds the **whole conversation** — spawn, handshake, call,
teardown — at `LIST_TIMEOUT_SECONDS`, because a server that hangs while starting
never reaches the call and `read_timeout_seconds` cannot see it. This was
already written correctly one layer up in `mcp_tools._talk()`; it moves down so
every caller inherits it instead of only the agent path.

`probe()` and the sync/action paths share one session per operation rather than
opening a second, which halves the process starts.

## 7. What is deliberately still open

- **Paging.** `MCPConnector.sync()` still ingests one page. The line this change
  draws — MCP is an ask/act surface, ingest belongs to the deep connectors and
  the REST form — makes that much less urgent, and it is tracked rather than
  quietly fixed here.
- **Remote server discovery.** The catalog names remote endpoints by hand. There
  is no registry to enumerate them from.
