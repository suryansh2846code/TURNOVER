"""Configured MCP servers, exposed to the agent loop as callable read tools.

The connector layer already knows how to *sync* a server (`mcp_source.py`) and
how to *change* something at one behind an approval (`perform()`). This is the
third thing a server is good for and the one the sync path deliberately cannot
do: answering a question that was only asked just now. A server exposing only
`search_messages` can never seed a brain — `classify_tools()` says so in as many
words — but it can answer "what did Ana say about the launch?" perfectly well,
and until now there was no way for the model to ask it.

So this module is a *surface*, not a new client: every line of protocol work is
`mcp_source`'s (`converse`, `probe`, `classify_tools`, `spec.permits`). What is
added here is the three properties an agent loop needs and a sync does not.

**It must be cheap to ask what exists.** `probe()` launches a subprocess per
server, and the loop asks on every turn. Uncached, a user with four connectors
pays four process spawns per message — which is the Models-drawer freeze
(5.7s + 4.4s, force-quit) moved inside chat. `list_tools()` is therefore
TTL-cached in the shape of `models/cache.py`, and `invalidate()` is wired into
the two functions that can change the answer.

**It must be reads only.** Writes keep the propose/confirm path they already
have: `mcp_action` is in `NEVER_UNATTENDED` because the text an agent is
reasoning about is text a stranger wrote, and an `<action>` in an email is an
instruction from that stranger. A write tool is still *listed* here — a
confirmation card has to be built from something — but `call_tool()` refuses it,
twice: once against what was cached, and once against what the server says at
the moment of the call.

**It must never take the turn down with it.** A server that is uninstalled,
signed out, hung or crashing returns a sentence the model can read and act on.
One broken server does not remove another server's tools, and no failure here
reaches the user as a traceback.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from ..log import get_logger
from ..models.cache import ttl_cached
from .mcp_errors import explain
from .mcp_source import (
    MCPServerSpec,
    classify_tools,
    get_server,
    list_servers,
)

log = get_logger(__name__)

#: How long a server's tool list is trusted. Long, deliberately: a server's
#: tools change when its *package* changes, which is a thing that happens at
#: install time and never mid-session — whereas the agent loop asks several
#: times a minute. Everything that really can change the answer (adding a
#: server, removing one, narrowing what it may read) calls `invalidate()`, so
#: the TTL is only the backstop for a server that was edited behind our back.
TOOLS_TTL_SECONDS = 300.0

#: A whole conversation — spawn, handshake, call, teardown — must finish inside
#: this. `mcp_source.CALL_TIMEOUT_SECONDS` (45s) is right for a sync running in
#: the background; it is much too long for a turn the user is watching, where a
#: silent 45s reads as a hang. Applied to the conversation rather than to the
#: call, because a server that dies during the handshake never reaches the call.
TURN_TIMEOUT_SECONDS = 20.0

#: The most tool output a model is given, in characters.
#:
#: There is no safe answer in tokens, because the model is the user's choice and
#: may have an 8k window or a 1M one. 8000 characters is roughly 2k tokens: a
#: few percent of a small window, invisible in a large one, and enough for tens
#: of records. The failure this prevents is not theoretical — an MCP tool that
#: answers with its vendor's raw JSON can return megabytes, and a single such
#: reply would evict the conversation, the recall block and the system prompt
#: before the model ever read it. Truncation is always *stated* in the text, so
#: the model knows to narrow its query rather than concluding it saw everything.
MAX_RESULT_CHARS = 8000

#: Tool names are passed through to providers that constrain them (OpenAI:
#: `^[a-zA-Z0-9_-]{1,64}$`), so the qualified name is built to the tightest of
#: those rules rather than to ours.
_NAME_MAX = 64
_NAME_OK = re.compile(r"[^A-Za-z0-9_-]")


@dataclass(frozen=True)
class MCPToolRef:
    """One callable tool on one configured server."""

    #: `mcp__<server_id>__<tool>`, sanitised and unique across every server.
    qualified_name: str
    server_id: str
    #: The connector's user-facing name. The acronym never reaches the UI.
    server_label: str
    #: The vendor's own tool name, which is what gets called.
    tool: str
    description: str
    #: JSON Schema exactly as the server published it.
    parameters: dict
    #: True means a caller must never offer this as a tool — it goes through
    #: the approval path (`mcp_action`) instead.
    writes: bool


# ── naming ──────────────────────────────────────────────────────────────────


def _sanitised(text: str) -> str:
    return _NAME_OK.sub("_", text) or "_"


def _qualify(server_id: str, tool: str, taken: set[str]) -> str:
    """A stable, legal, unique name for one server's tool.

    Stable matters more than pretty: the model sees this name, may repeat it a
    round later, and the loop's repeat detector compares call signatures. So the
    shortened form is derived from a digest of the *exact* ids rather than from
    a counter, which would move every time a server list was reordered.
    """
    base = f"mcp__{_sanitised(server_id)}__{_sanitised(tool)}"
    if len(base) <= _NAME_MAX and base not in taken:
        return base

    digest = hashlib.sha256(f"{server_id}\0{tool}".encode()).hexdigest()[:6]
    name = f"{base[:_NAME_MAX - 7]}_{digest}"
    bump = 0
    while name in taken:                     # pragma: no cover - needs a digest clash
        bump += 1
        name = f"{base[:_NAME_MAX - 9]}_{digest}{bump:02d}"
    return name


# ── talking to a server, with a ceiling ─────────────────────────────────────


def _talk(spec: MCPServerSpec, action, timeout: float | None = None):
    """`mcp_source.converse`, but the whole conversation is time-boxed.

    `converse` bounds nothing on its own and `call_tool`'s `read_timeout_seconds`
    only bounds the reply — a server that hangs while *starting* never gets as
    far as a call, and would hold the turn open forever. `anyio.fail_after`
    around the entire session cancels the scope, which unwinds `stdio_client`
    and terminates the subprocess with it.
    """
    import anyio

    # Late, so a test can count real spawns.
    from . import mcp_source

    ceiling = TURN_TIMEOUT_SECONDS if timeout is None else timeout

    async def guarded():
        with anyio.fail_after(ceiling):
            return await mcp_source._converse(spec, action)

    return anyio.run(guarded)


async def _list(session):
    """One listing helper for the whole layer.

    Delegates rather than calling `session.list_tools()` again, so this path
    inherits the tolerance for servers whose schema the SDK's model rejects —
    a second copy here is how the agent saw zero tools from a server the
    Connectors page had just reported as working.
    """
    from .mcp_source import list_tools_in

    return await list_tools_in(session)


def _list_every(specs: list[MCPServerSpec]) -> dict[str, list]:
    """Every server's tools, gathered at once and bounded one server at a time.

    Sequentially, a user with four connectors and one uninstalled binary waits
    out that binary's whole timeout before the other three are even started —
    N servers × the ceiling, on a turn somebody is watching, which is the freeze
    this module exists to avoid rather than a smaller version of it. One task
    group makes the wait the slowest server's, not the sum.

    Each task swallows its own failure. A raise inside a task group cancels its
    siblings, so letting one escape would take every other server's tools with
    it — the exact property this is supposed to guarantee.
    """
    import anyio

    # Late, so a test can count real spawns.
    from . import mcp_source

    gathered: dict[str, list] = {}

    async def one(spec: MCPServerSpec) -> None:
        try:
            with anyio.fail_after(mcp_source.LIST_TIMEOUT_SECONDS):
                gathered[spec.id] = await mcp_source._converse(spec, _list)
        except Exception as exc:
            log.debug("MCP tool listing failed for %s: %s", spec.id, exc)

    async def everyone() -> None:
        async with anyio.create_task_group() as group:
            for spec in specs:
                group.start_soon(one, spec)

    anyio.run(everyone)
    return gathered


def _schema_of(tool: Any) -> dict:
    schema = getattr(tool, "input_schema", None)
    if not isinstance(schema, dict):
        schema = getattr(tool, "inputSchema", None)
    if not isinstance(schema, dict):
        # Not every server publishes one. An empty object schema is the honest
        # reading of "takes no arguments" and is what every provider accepts.
        return {"type": "object", "properties": {}}
    return schema


# ── what the agent may call ─────────────────────────────────────────────────


@ttl_cached(TOOLS_TTL_SECONDS)
def list_tools() -> list[MCPToolRef]:
    """Every tool on every configured server, as the agent loop sees them.

    Never raises, and never waits on one server longer than it has to. A
    server that will not start contributes nothing and is logged; the servers
    either side of it are unaffected and were being asked at the same time,
    because a user with four connectors losing all four — or waiting out all
    four timeouts — over one uninstalled binary is the same class of bug as a
    sync aborting on one bad item.

    Tools the user has excluded (`spec.allowed_tools`) are left out entirely
    rather than returned locked: least privilege is about what can be reached,
    and a name the model cannot call is only an invitation to try.
    """
    refs: list[MCPToolRef] = []
    taken: set[str] = set()

    specs = list_servers()
    gathered = _list_every(specs)

    for spec in specs:
        tools = gathered.get(spec.id)
        if not tools:
            continue

        kinds = classify_tools(tools)
        writes = set(kinds.write)
        for tool in tools:
            name = getattr(tool, "name", "")
            if not name or not spec.permits(name):
                continue
            qualified = _qualify(spec.id, name, taken)
            taken.add(qualified)
            refs.append(MCPToolRef(
                qualified_name=qualified,
                server_id=spec.id,
                server_label=spec.name,
                tool=name,
                description=(getattr(tool, "description", "") or "").strip(),
                parameters=_schema_of(tool),
                writes=name in writes,
            ))
    return refs


def write_tools() -> list[MCPToolRef]:
    """The tools a model may **propose** but never call.

    `list_tools()` already discovers these — a confirmation card has to be built
    from something — and `call_tool()` refuses them. What was missing is anyone
    asking for them: an agent cannot propose an action whose name it was never
    told, which is why connector writes existed end to end and no agent could
    originate one.

    Reads and writes come from the same cached pass, so asking for this costs
    nothing on top of the tool list the loop already built.
    """
    return [ref for ref in list_tools() if ref.writes]


def invalidate() -> None:
    """Forget the cached tool list.

    Called whenever the answer can have changed — a server added, a server
    removed, or what a server is permitted to read narrowed. Without this the
    user disables a tool and the model keeps being offered it for five minutes,
    which is the same lie as a "Connected" badge with no credential behind it.
    """
    list_tools.cache_clear()            # type: ignore[attr-defined]


# ── calling one ─────────────────────────────────────────────────────────────


def _find(qualified_name: str) -> MCPToolRef | None:
    return next((r for r in list_tools()
                 if r.qualified_name == qualified_name), None)


def _rendered(answer: Any, label: str) -> str:
    """A tool's reply as text a model can read.

    `_records()` already knows the three shapes servers answer in (structured
    JSON, a JSON document inside a text block, prose), so this is only the last
    step: keep prose as prose — it is what the user would have read — and give
    everything else stable, indented JSON.
    """
    from .mcp_source import _records

    records = _records(answer)
    if not records:
        return f"{label} returned nothing."
    if len(records) == 1 and isinstance(records[0], str):
        text = records[0]
    else:
        text = json.dumps(records, ensure_ascii=False, indent=2, default=str)
    return _truncated(text, label)


def _truncated(text: str, label: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return (text[:MAX_RESULT_CHARS].rstrip()
            + f"\n\n[Truncated: showed the first {MAX_RESULT_CHARS:,} of "
              f"{len(text):,} characters returned by {label}. Ask a narrower "
              "question to see the rest.]")


def call_tool(qualified_name: str, arguments: dict) -> str:
    """Run one **read** tool and return what it said, as text.

    Reads only, and it fails closed the way `perform(confirmed=…)` does: a name
    that is not on the list, a tool the user has not permitted, or anything
    classified as a write is refused without a process ever being started.

    The refusal is prose rather than an exception because the caller is a model:
    it needs to know it may not do that and carry on, and an exception here
    would end a turn the user is watching.
    """
    ref = _find(qualified_name)
    if ref is None:
        return (f"There is no connector tool called `{qualified_name}`. "
                "Use one of the tools you were given.")
    if ref.writes:
        return (f"`{ref.tool}` changes something in {ref.server_label}, so it "
                "cannot be run from here. Propose it as an action and the user "
                "will be asked to approve it.")

    spec = get_server(ref.server_id)
    if spec is None:
        return (f"{ref.server_label} is no longer connected. "
                "It can be added again in Connectors.")
    if not spec.permits(ref.tool):
        return f"{ref.server_label} is not allowed to use `{ref.tool}`."

    async def _call(session):
        # The cached list is a convenience, not the authority. Re-reading the
        # server's own tools inside the session we already opened costs one
        # message and no extra process, and it is what stops a tool that became
        # a write since the cache was filled from being called as a read.
        live = classify_tools(await _list(session))
        if ref.tool in live.write:
            return None
        from .mcp_source import call_tool_in

        return await call_tool_in(session, ref.tool, arguments or {},
                                  TURN_TIMEOUT_SECONDS)

    try:
        answer = _talk(spec, _call)
    except Exception as exc:
        log.debug("MCP call %s failed: %s", qualified_name, exc)
        return explain(exc, ref.server_label)

    if answer is None:
        invalidate()
        return (f"`{ref.tool}` now changes something in {ref.server_label}, so "
                "it was not run. Propose it as an action instead.")
    if getattr(answer, "is_error", False):
        return (f"{ref.server_label} could not answer `{ref.tool}`. "
                "It may need different arguments.")
    return _rendered(answer, ref.server_label)
