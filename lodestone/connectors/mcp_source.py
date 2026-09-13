"""Connectors backed by an MCP server.

This is the answer to breadth. Writing a connector by hand is right for the six
sources the brain is actually built from and hopeless for the long tail, and the
alternative everyone reaches for — a hosted broker like Composio — is the exact
trade this product exists to refuse: it puts a third party's cloud between the
user's mail and the user's machine, and its consent screen carries the broker's
name instead of the vendor's. Turnstone made that trade; `TURNSTONE-TEARDOWN.md`
records what it cost them.

A local MCP server has none of that. It is a subprocess. It talks to its own
vendor over the user's own credential, the data lands on the user's disk, and
the sign-in it runs is the vendor's own — which is why **we register no OAuth
client and need no verification**, the same reason a "Sign in with Claude"
button works through the Claude CLI.

To the user this is a connector. The acronym never reaches the UI, exactly as
"vendor CLI" never reaches the sign-in card.

**What this deliberately does not promise.** MCP tools are shaped to answer one
question for a model, not to page a mailbox into a database. A server exposing
`list_messages` can seed a brain; one exposing only `search_messages` cannot,
and must say so rather than sync nothing and report success. `classify_tools()`
is that distinction, and it is drawn from the one signal that actually means it:
whether a tool can be called with no arguments.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..config import get_settings
from ..log import get_logger, suppressed
from .base import Connector, SyncResult

log = get_logger(__name__)

#: How long any single MCP conversation may take. A server that hangs must not
#: hang the sync — the thread it runs on is one the UI also needs.
CALL_TIMEOUT_SECONDS = 45.0
LIST_TIMEOUT_SECONDS = 20.0

#: Tool-name stems that mean "give me the records". Checked as a fallback to
#: the argument test below, never instead of it: a name is a hint, a required
#: `query` parameter is proof.
_BULK_HINTS = ("list", "recent", "all", "fetch", "export", "read", "get_many",
               "history", "items", "entries")

#: Arguments a listing tool may require without ceasing to be a listing tool.
_PAGING_ARGS = {"cursor", "page", "page_token", "offset", "start", "limit",
                "count", "max_results", "per_page", "page_size", "after"}


@dataclass
class MCPServerSpec:
    """How to start one server, and what to read out of it."""

    id: str
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    #: Tool to call for records. Empty means "work it out from the server".
    sync_tool: str = ""
    #: Field in each record to use as a title, if the server returns objects.
    title_field: str = ""
    #: Tools this connector may use at all. Empty means "every readable tool".
    #: Least privilege is only real if the user can narrow it, and they can only
    #: narrow what they were shown — `mcp_catalog.describe()` is that list.
    allowed_tools: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> MCPServerSpec:
        return cls(
            id=raw["id"], name=raw.get("name") or raw["id"],
            command=raw["command"], args=list(raw.get("args") or []),
            env=dict(raw.get("env") or {}),
            sync_tool=raw.get("sync_tool") or "",
            title_field=raw.get("title_field") or "",
            allowed_tools=list(raw.get("allowed_tools") or []),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "command": self.command,
                "args": self.args, "env": self.env, "sync_tool": self.sync_tool,
                "title_field": self.title_field,
                "allowed_tools": self.allowed_tools}

    def permits(self, tool: str) -> bool:
        """May this connector use that tool? Empty allow-list means anything."""
        return not self.allowed_tools or tool in self.allowed_tools


# ── the spec store ──────────────────────────────────────────────────────────


def _specs_path():
    return get_settings().home / "mcp_servers.json"


def _load() -> dict[str, dict]:
    with suppressed("reading the saved MCP connector list"):
        return json.loads(_specs_path().read_text())
    return {}


def _save(specs: dict[str, dict]) -> None:
    path = _specs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(specs, indent=2))


def list_servers() -> list[MCPServerSpec]:
    return [MCPServerSpec.from_dict(v) for v in _load().values()]


def get_server(server_id: str) -> MCPServerSpec | None:
    raw = _load().get(server_id)
    return MCPServerSpec.from_dict(raw) if raw else None


def _forget_tools() -> None:
    """Drop the agent-facing tool cache after the saved servers change.

    `mcp_tools.list_tools()` is TTL-cached because the agent loop asks on every
    turn, so without this a server the user just added stays invisible — and a
    tool they just disallowed stays callable — for the length of the TTL. Late
    import: `mcp_tools` is built on this module.
    """
    with suppressed("flushing the MCP tool cache"):
        from .mcp_tools import invalidate

        invalidate()


def upsert_server(spec: MCPServerSpec) -> MCPServerSpec:
    specs = _load()
    specs[spec.id] = spec.as_dict()
    _save(specs)
    _forget_tools()
    return spec


def delete_server(server_id: str) -> bool:
    specs = _load()
    if server_id not in specs:
        return False
    del specs[server_id]
    _save(specs)
    _forget_tools()
    return True


# ── what a server can actually do ───────────────────────────────────────────


@dataclass
class ToolKinds:
    """What the tools a server exposes are good for.

    `bulk` can seed a brain; `query` can only answer a question asked of it;
    `write` changes something at the vendor and is never called by a sync.
    """

    bulk: list[str] = field(default_factory=list)
    query: list[str] = field(default_factory=list)
    write: list[str] = field(default_factory=list)

    @property
    def can_sync(self) -> bool:
        return bool(self.bulk)

    def why_not(self, label: str) -> str:
        """The sentence shown where the user is looking when a sync is not on."""
        if self.query:
            return (f"{label} can answer questions but cannot list its records, "
                    "so it is searched on demand instead of being synced.")
        return f"{label} exposes no readable tools."


def _required(schema: dict | None) -> set[str]:
    return set((schema or {}).get("required") or [])


def _is_write(name: str, annotations: Any) -> bool:
    """Writes are identified from the server's own declaration first.

    MCP lets a tool state `readOnlyHint`. Trusting the name alone would classify
    `update_cache` as a write and `send` as a read, and getting it wrong in that
    direction means a sync mutating the user's account.
    """
    hint = getattr(annotations, "read_only_hint", None)
    if hint is True:
        return False
    if getattr(annotations, "destructive_hint", None) is True:
        return True
    lowered = name.lower()
    return any(w in lowered for w in
               ("create", "update", "delete", "send", "post", "write", "add",
                "remove", "archive", "move", "set_", "edit", "reply"))


def classify_tools(tools: list[Any]) -> ToolKinds:
    """Sort a server's tools into what a sync may use.

    The test that matters is **can this be called with no arguments** — a tool
    that requires a `query` is a search box, and calling it with a guess would
    invent data rather than read it. Names are a tiebreak, never the rule: a
    server naming its lister `entries` is common, and a server naming a search
    `list_matching` is not rare either.
    """
    kinds = ToolKinds()
    for tool in tools:
        name = getattr(tool, "name", "")
        if not name:
            continue
        if _is_write(name, getattr(tool, "annotations", None)):
            kinds.write.append(name)
            continue
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
        required = _required(schema if isinstance(schema, dict) else None)
        callable_bare = not (required - _PAGING_ARGS)
        if callable_bare and any(h in name.lower() for h in _BULK_HINTS):
            kinds.bulk.append(name)
        elif callable_bare and not required:
            # No required arguments at all and no recognised name: still a
            # listing, because there is nothing else a zero-argument read does.
            kinds.bulk.append(name)
        else:
            kinds.query.append(name)
    return kinds


# ── talking to a server ─────────────────────────────────────────────────────


async def _converse(spec: MCPServerSpec, action):
    """Open a session, hand it to `action`, and always close the process."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=spec.command, args=list(spec.args), env=dict(spec.env) or None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await action(session)


def converse(spec: MCPServerSpec, action):
    """`_converse` from synchronous code.

    Connectors run in a worker thread (see `api/concurrency.py`), so there is no
    running loop here to clash with — `anyio.run` owns one for the call and
    tears it down with the subprocess.
    """
    import anyio

    return anyio.run(_converse, spec, action)


def probe(spec: MCPServerSpec) -> tuple[ToolKinds | None, str]:
    """What can this server do, or why can we not tell?

    Returns `(None, reason)` rather than raising, because the caller is a UI
    that must say what happened in the place the user is looking.
    """
    from .mcp_errors import explain

    async def _list(session):
        with_timeout = await session.list_tools()
        return list(with_timeout.tools)

    try:
        return classify_tools(converse(spec, _list)), ""
    except Exception as exc:
        log.debug("MCP probe failed for %s: %s", spec.id, exc)
        return None, explain(exc, spec.name)


def _records(result: Any) -> list[Any]:
    """Pull records out of whatever shape the tool answered with.

    Servers answer in three shapes and all three are common: structured JSON,
    a JSON document inside a text block, or plain prose. The last is still
    worth keeping — it is what the user would have read.
    """
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, list):
        return structured
    if isinstance(structured, dict):
        found = _list_inside(structured)
        if found is not None:
            return found
        # A tool that returns a JSON *string* arrives double-wrapped: the SDK
        # puts the string under `result`, and the records are inside the string.
        # Falling through to the content blocks below is what unwraps it, and
        # is why this does not simply store the wrapper as one record.
        if not _only_a_string(structured):
            return [structured]

    out: list[Any] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            out.append(text)
            continue
        if isinstance(parsed, list):
            out.extend(parsed)
        elif isinstance(parsed, dict):
            nested = next((parsed[k] for k in
                           ("items", "results", "records", "data", "entries")
                           if isinstance(parsed.get(k), list)), None)
            out.extend(nested if nested is not None else [parsed])
        else:
            out.append(text)
    return out


#: Keys servers put their records under. `result` is what the MCP SDK itself
#: uses when a tool returns a bare list, which is the most common case of all
#: and the one a hand-written key list is most likely to miss.
_RECORD_KEYS = ("result", "items", "results", "records", "data", "entries",
                "messages", "rows", "values")


def _list_inside(payload: dict) -> list | None:
    """The list of records inside a wrapper object, if there is one.

    Falls back to "a single key holding a list" rather than giving up, because
    servers name that key whatever suits their domain (`issues`, `pages`,
    `commits`) and no fixed list will ever cover them all.
    """
    for key in _RECORD_KEYS:
        if isinstance(payload.get(key), list):
            return payload[key]
    lists = [v for v in payload.values() if isinstance(v, list)]
    if len(lists) == 1 and len(payload) == 1:
        return lists[0]
    return None


def _only_a_string(payload: dict) -> bool:
    """Is this wrapper nothing but a single string value?"""
    return len(payload) == 1 and isinstance(next(iter(payload.values())), str)


def _as_text(record: Any, *, title_field: str, label: str) -> tuple[str, str]:
    """A record as (title, text) for the brain."""
    if isinstance(record, str):
        first = record.strip().split("\n", 1)[0]
        return (first[:120] or label), record
    if isinstance(record, dict):
        title = ""
        if title_field and record.get(title_field) is not None:
            title = str(record[title_field])
        else:
            for key in ("title", "name", "subject", "summary", "id"):
                if record.get(key) is not None:
                    title = str(record[key])
                    break
        body = record.get("text") or record.get("body") or record.get("content")
        if not isinstance(body, str):
            body = json.dumps(record, ensure_ascii=False, indent=2)[:4000]
        return (title or label), f"{label} — {title or ''}\n\n{body}".strip()
    return label, f"{label}\n\n{record}"


# ── the connector ───────────────────────────────────────────────────────────


class MCPConnector(Connector):
    """One connector per configured server (name = 'mcp:<id>')."""

    auto_sync = True
    # A watermark would have to be a parameter the tool accepts, and there is no
    # agreed name for one across servers. Dedup carries the repeat pass.
    incremental = False

    def __init__(self, spec: MCPServerSpec, store=None) -> None:
        super().__init__(store)
        self.spec = spec
        self.name = f"mcp:{spec.id}"
        self.label = spec.name

    def is_configured(self) -> tuple[bool, str]:
        """A server that will not start must never read as Connected.

        This actually launches it, because the only honest test of "can this
        run" is running it — a binary that was uninstalled, a credential that
        expired, and a server that crashes on boot all look identical from the
        spec alone.
        """
        if not self.spec.command:
            return False, "this connector has no command to run"
        kinds, reason = probe(self.spec)
        if kinds is None:
            return False, reason
        if not kinds.can_sync and not self.spec.sync_tool:
            return False, kinds.why_not(self.label)
        return True, ""

    # ── actions (writes) ────────────────────────────────────────────────

    def available_actions(self) -> list[dict[str, str]]:
        """Write tools this connector is permitted to offer, for confirmation.

        Returned rather than executed: nothing here changes anything at the
        vendor. The list is what a confirmation card is built from, which is the
        only way a user can be shown what they are agreeing to.
        """
        kinds, _ = probe(self.spec)
        if kinds is None:
            return []
        return [{"tool": name, "connector": self.name, "label": self.label}
                for name in kinds.write if self.spec.permits(name)]

    def perform(self, tool: str, arguments: dict[str, Any] | None = None, *,
                confirmed: bool = False) -> dict[str, Any]:
        """Run a write tool — only after the user has confirmed *this* action.

        `confirmed` is a required, explicit gate rather than a default, so a
        caller that forgets it fails closed. Connectors have been read-only by
        design (decision C1) and this is the first path that changes something
        at the vendor; the agent reaches it the same way it reaches sending an
        email — by proposing an action the user clicks to approve, never by
        calling it mid-turn.
        """
        from .mcp_errors import explain

        if not confirmed:
            return {"ok": False,
                    "error": "This action needs your confirmation first."}
        if not self.spec.permits(tool):
            return {"ok": False,
                    "error": f"{self.label} is not allowed to use `{tool}`."}

        kinds, reason = probe(self.spec)
        if kinds is None:
            return {"ok": False, "error": reason}
        if tool not in kinds.write and tool not in kinds.bulk and tool not in kinds.query:
            return {"ok": False,
                    "error": f"{self.label} has no `{tool}` to run."}

        async def _call(session):
            return await session.call_tool(
                tool, dict(arguments or {}),
                read_timeout_seconds=CALL_TIMEOUT_SECONDS)

        try:
            answer = converse(self.spec, _call)
        except Exception as exc:
            return {"ok": False, "error": explain(exc, self.label)}
        if getattr(answer, "is_error", False):
            return {"ok": False,
                    "error": f"{self.label} could not complete that action."}
        records = _records(answer)
        detail = records[0] if len(records) == 1 else records
        return {"ok": True, "detail": detail}

    def sync(self, *, since: str | None = None, limit: int | None = None,
             full_history: bool = False, cancel=None, progress=None,
             interactive: bool = True, **_: Any) -> SyncResult:
        from .mcp_errors import explain

        result = SyncResult(connector=self.name)
        max_items = limit or 200

        try:
            kinds, reason = probe(self.spec)
            if kinds is None:
                result.errors.append(reason)
                result.detail = "could not start"
                return self._finish(result)

            permitted = [t for t in kinds.bulk if self.spec.permits(t)]
            tool = self.spec.sync_tool or (permitted[0] if permitted else "")
            if tool and not self.spec.permits(tool):
                result.errors.append(
                    f"{self.label} is not allowed to use its `{tool}` tool. "
                    "Change what it may read in Connectors.")
                result.detail = "not permitted"
                return self._finish(result)
            if not tool:
                # Not an error — a real and permanent property of this server,
                # and saying so is the difference between "search-only" and
                # "broken". Silently reporting success with zero records is how
                # a user concludes the app does not work.
                result.detail = kinds.why_not(self.label)
                result.errors.append(result.detail)
                return self._finish(result)

            async def _call(session):
                return await session.call_tool(
                    tool, {}, read_timeout_seconds=CALL_TIMEOUT_SECONDS)

            answer = converse(self.spec, _call)
            if getattr(answer, "is_error", False):
                result.errors.append(
                    f"{self.label} reported a problem reading its records.")
                result.detail = "sync failed"
                return self._finish(result)

            records = _records(answer)
            from ..brain import get_brain
            brain = get_brain()

            def ingest(record) -> int:
                title, text = _as_text(record, title_field=self.spec.title_field,
                                       label=self.label)
                if not text.strip():
                    return 0
                out = brain.ingest(text, source=self.name, kind="record",
                                   title=title, fast=True)
                return out["memories"]

            self.each_guarded(records[:max_items], result, ingest,
                              cancel=cancel, progress=progress)
            result.detail = result.detail or (
                f"{len(records)} records from {self.label}")
        except Exception as exc:
            result.errors.append(explain(exc, self.label))
            result.detail = "sync failed"
        return self._finish(result)
