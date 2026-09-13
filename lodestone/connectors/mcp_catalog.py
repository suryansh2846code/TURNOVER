"""The connectors we offer, and the ones we tell the truth about instead.

Two jobs, and the second matters as much as the first.

**Offering one safely.** An MCP server is third-party code that runs as the user
and reads their accounts, so it gets the rules `models/cli_manager.py` already
established for vendor CLIs: a **pinned version**, never `@latest` — an
unpinned package is a supply chain that changes under the user without anyone
deciding — and **verified before it is enabled**, by actually starting it and
reading its tool list, because a spec that parses proves nothing about a server
that will not boot.

**Refusing one honestly.** Some sources cannot be read by anybody, and a UI that
simply omits them teaches the user that the app is missing features. LinkedIn is
the case that matters: its User Agreement §8.2 bans automated access, feed and
member data sit behind a partner programme individual developers cannot join,
and every community server is a scraper — after the late-2025 crackdown, one
built on a browser fork made to evade bot detection. Shipping that would put a
**ban on the user's account, not ours**. Composio's LinkedIn toolkit is
write-only for exactly the same reason, so this is a platform limit and not a
gap in our approach. `BLOCKED` carries the sentence to show instead, which is
"never show a control that cannot work" applied to a whole source.
"""
from __future__ import annotations

from dataclasses import dataclass

from .mcp_source import MCPServerSpec, probe, upsert_server


@dataclass(frozen=True)
class CatalogEntry:
    """A connector the user can add, pinned to a version we have named."""

    id: str
    name: str
    #: How it is launched. `npx`/`uvx` fetch on demand; the version is part of
    #: the package spec so the fetch is reproducible.
    command: str
    args: tuple[str, ...]
    #: Environment the server needs, as (name, human explanation) pairs. The UI
    #: asks for these; nothing here is ever stored in the catalog itself.
    needs_env: tuple[tuple[str, str], ...] = ()
    #: First-party means the vendor publishes it. Community servers are offered
    #: with that stated, never silently mixed in.
    first_party: bool = True
    notes: str = ""

    @property
    def pinned(self) -> bool:
        """Is every package reference version-locked?

        `@latest` or a bare package name means the code that runs tomorrow is
        not the code reviewed today.
        """
        for arg in self.args:
            if arg.startswith("-"):
                continue
            if arg.endswith(("@latest", "@*")):
                return False
            if "@" in arg.lstrip("@").replace("/", "") or "==" in arg:
                return True
        return False

    def to_spec(self) -> MCPServerSpec:
        return MCPServerSpec(id=self.id, name=self.name, command=self.command,
                             args=list(self.args))


@dataclass(frozen=True)
class BlockedSource:
    """A source we will not offer, and the reason to show where it would be."""

    id: str
    name: str
    reason: str


#: Vetted connectors. Versions are pinned deliberately; bumping one is a change
#: somebody makes on purpose, which is the entire point.
CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        id="filesystem", name="Files (MCP)",
        command="npx", args=("-y", "@modelcontextprotocol/server-filesystem@0.6.2"),
        notes="Reads a folder you choose. The built-in Local Files connector is "
              "usually the better choice; this exists for parity.",
    ),
    CatalogEntry(
        id="github", name="GitHub",
        command="npx", args=("-y", "@modelcontextprotocol/server-github@0.6.2"),
        needs_env=(("GITHUB_PERSONAL_ACCESS_TOKEN",
                    "A GitHub token with read access to the repos you want."),),
    ),
    CatalogEntry(
        id="slack", name="Slack",
        command="npx", args=("-y", "@modelcontextprotocol/server-slack@0.6.2"),
        needs_env=(("SLACK_BOT_TOKEN", "A Slack bot token for your workspace."),
                   ("SLACK_TEAM_ID", "Your Slack workspace ID.")),
        notes="A bot can only read the channels it has been invited to.",
    ),
    CatalogEntry(
        id="sentry", name="Sentry",
        command="npx", args=("-y", "@modelcontextprotocol/server-sentry@0.6.2"),
        needs_env=(("SENTRY_AUTH_TOKEN", "A Sentry auth token."),),
    ),
)

#: Sources that cannot be read by anyone, with the sentence to show instead.
#: Each of these is a platform decision, not a limitation of this approach — a
#: hosted broker hits exactly the same wall.
BLOCKED: tuple[BlockedSource, ...] = (
    BlockedSource(
        "linkedin", "LinkedIn",
        "LinkedIn does not allow apps to read your feed, connections or "
        "messages — its terms ban automated access, and the tools that claim "
        "to do it work by evading detection and can get your account banned. "
        "No app can offer this, including the ones that say they do.",
    ),
    BlockedSource(
        "whatsapp", "WhatsApp",
        "WhatsApp has no API for reading your personal chats. Messages on this "
        "Mac can be read through the iMessage connector instead.",
    ),
    BlockedSource(
        "instagram", "Instagram",
        "Instagram's API covers business accounts only, and does not expose a "
        "personal feed or direct messages to any app.",
    ),
)

BY_ID = {entry.id: entry for entry in CATALOG}
BLOCKED_BY_ID = {source.id: source for source in BLOCKED}


def unpinned() -> list[str]:
    """Catalog ids whose packages are not version-locked.

    Exposed so a test can assert the list is empty rather than a reviewer
    having to notice an `@latest` in a diff.
    """
    return [entry.id for entry in CATALOG if not entry.pinned]


def add_from_catalog(entry_id: str, env: dict[str, str] | None = None
                     ) -> tuple[MCPServerSpec | None, str]:
    """Verify a catalog entry actually runs, then save it.

    Returns `(None, reason)` when it does not. **Nothing is saved on failure**:
    the vendor-CLI rule is that a download which fails verification is never
    linked, and a connector that cannot start must never appear as Connected.
    """
    entry = BY_ID.get(entry_id)
    if entry is None:
        blocked = BLOCKED_BY_ID.get(entry_id)
        if blocked is not None:
            return None, blocked.reason
        return None, "That connector is not in the catalog."

    spec = entry.to_spec()
    spec.env = dict(env or {})

    missing = [name for name, _ in entry.needs_env if not spec.env.get(name)]
    if missing:
        needed = ", ".join(missing)
        return None, f"{entry.name} still needs {needed} before it can connect."

    kinds, reason = probe(spec)
    if kinds is None:
        return None, reason
    if not kinds.can_sync:
        return None, kinds.why_not(entry.name)

    upsert_server(spec)
    return spec, ""


def describe(entry_id: str) -> dict:
    """What a connector would be allowed to do, before it is enabled.

    Least privilege needs the user to be able to see the tools first — an
    install button that says only "Connect" is asking for consent to something
    nobody has been shown.
    """
    entry = BY_ID.get(entry_id)
    if entry is None:
        return {"id": entry_id, "available": False,
                "reason": (BLOCKED_BY_ID[entry_id].reason
                           if entry_id in BLOCKED_BY_ID
                           else "That connector is not in the catalog.")}
    kinds, reason = probe(entry.to_spec())
    return {
        "id": entry.id,
        "name": entry.name,
        "available": kinds is not None,
        "reason": reason,
        "first_party": entry.first_party,
        "notes": entry.notes,
        "needs_env": [{"name": n, "help": h} for n, h in entry.needs_env],
        "reads": list(kinds.bulk + kinds.query) if kinds else [],
        "writes": list(kinds.write) if kinds else [],
        "can_sync": bool(kinds and kinds.can_sync),
    }
