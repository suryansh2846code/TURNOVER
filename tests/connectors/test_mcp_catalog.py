"""The catalog's safety rules, and the ones it refuses to break.

An MCP server is third-party code running as the user against their accounts.
That puts it in the same category as the vendor CLIs `cli_manager.py` installs,
and it inherits the same rules — which are only rules if something checks them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from chitragupta.connectors import mcp_catalog
from chitragupta.connectors.mcp_source import MCPConnector, MCPServerSpec, list_servers

SERVER = str(Path(__file__).parent / "fake_mcp_server.py")


# ── 3.2 — the supply-chain rules ───────────────────────────────────────────


def test_every_catalog_entry_is_version_pinned():
    """`@latest` means the code that runs tomorrow is not the code reviewed
    today. Asserted here so it cannot be reintroduced by a diff nobody reads
    closely."""
    assert mcp_catalog.unpinned() == [], (
        f"unpinned catalog entries: {mcp_catalog.unpinned()}")


@pytest.mark.parametrize("entry", mcp_catalog.CATALOG,
                         ids=[e.id for e in mcp_catalog.CATALOG])
def test_no_entry_pipes_a_script_into_a_shell(entry):
    """The rule that made the vendor-CLI installs auditable: fetch the artifact,
    never `curl … | bash`.

    A remote entry satisfies this by construction — it launches nothing at all,
    which is the strongest version of the same guarantee and the reason most of
    the catalog moved to that shape.
    """
    blob = " ".join((entry.command, *entry.args)).lower()
    assert "|" not in blob and "curl" not in blob and "sh -c" not in blob

    if entry.is_remote:
        assert not entry.command and not entry.args, (
            f"{entry.id} is remote and should run nothing locally")
        return
    assert entry.command in ("npx", "uvx", "node", "python", sys.executable), (
        f"{entry.id} launches via an unexpected program: {entry.command}")


def test_a_server_that_will_not_start_is_never_saved():
    """A failed verification must leave nothing behind. The vendor-CLI rule is
    that a download failing `--version` is never linked; a connector that
    cannot boot must never appear in the user's list."""
    spec = MCPServerSpec(id="broken", name="Broken",
                         command="/nonexistent/nope", args=[])
    from chitragupta.connectors.mcp_source import probe

    kinds, reason = probe(spec)

    assert kinds is None and reason
    assert list_servers() == [], "a failed probe left a connector saved"


def test_adding_an_unknown_entry_is_refused():
    spec, reason = mcp_catalog.add_from_catalog("not-a-real-connector")

    assert spec is None
    assert "catalog" in reason


def test_a_missing_credential_is_named_before_anything_runs():
    """The field is named the way the user saw it on the form.

    This used to assert the variable name (`GITHUB_PERSONAL_ACCESS_TOKEN`) was
    in the sentence. A variable name is an internal, and `/CLAUDE.md` is
    explicit that one must never reach user-facing text — so the message names
    the label that sat above the box they left empty. What is being frozen here
    is unchanged: the gap is named, and nothing is saved.
    """
    spec, reason = mcp_catalog.add_from_catalog("github", env={})

    assert spec is None
    label = mcp_catalog.BY_ID["github"].needs_env[0].label
    assert label.lower() in reason.lower()
    assert "GITHUB_TOKEN" not in reason, "a variable name is not for a person"
    assert list_servers() == []


# ── 3.4 — the sources nobody can offer ─────────────────────────────────────


@pytest.mark.parametrize("blocked", mcp_catalog.BLOCKED,
                         ids=[b.id for b in mcp_catalog.BLOCKED])
def test_a_blocked_source_explains_itself(blocked):
    """"Never show a control that cannot work" applied to a whole source.

    Omitting LinkedIn silently teaches the user the app is missing a feature.
    Saying why — and that no app can do it — is the honest version.
    """
    spec, reason = mcp_catalog.add_from_catalog(blocked.id)

    assert spec is None
    assert reason == blocked.reason
    assert len(reason) > 60, "a refusal with no explanation is just a dead end"


def test_linkedin_says_the_risk_is_to_the_user():
    """The reason this is refused rather than shipped behind a warning: the ban
    lands on the user's account, not ours."""
    reason = mcp_catalog.BLOCKED_BY_ID["linkedin"].reason.lower()

    assert "ban" in reason
    assert "terms" in reason or "automated access" in reason


def test_blocked_sources_are_not_in_the_offered_catalog():
    offered = {e.id for e in mcp_catalog.CATALOG}
    assert offered.isdisjoint(mcp_catalog.BLOCKED_BY_ID)


# ── 3.3 — least privilege ──────────────────────────────────────────────────


def spec_for(mode: str, **over) -> MCPServerSpec:
    return MCPServerSpec(id=over.pop("id", mode), name=f"{mode.title()} Source",
                         command=sys.executable, args=[SERVER, mode], **over)


def test_describe_shows_reads_and_writes_before_connecting():
    """An install button that says only "Connect" asks for consent to something
    nobody has been shown."""
    import chitragupta.connectors.mcp_catalog as cat

    entry = cat.CatalogEntry(id="writes", name="Writes Source",
                             command=sys.executable, args=(SERVER, "writes"))
    cat.BY_ID["writes"] = entry
    try:
        described = cat.describe("writes")
    finally:
        del cat.BY_ID["writes"]

    assert described["available"]
    assert "list_records" in described["reads"]
    assert "delete_record" in described["writes"]
    assert "send_message" in described["writes"]
    assert described["can_sync"]


def test_describe_explains_a_blocked_source_instead_of_failing():
    described = mcp_catalog.describe("linkedin")

    assert described["available"] is False
    assert "ban" in described["reason"].lower()


def test_an_allow_list_restricts_what_a_sync_may_call():
    conn = MCPConnector(spec_for("listing", allowed_tools=["something_else"]))

    result = conn.sync(interactive=False)

    assert result.added == 0
    assert result.errors, "a disallowed tool synced anyway"


def test_an_empty_allow_list_permits_the_readable_tools():
    """The default must stay usable — least privilege that breaks the common
    case gets turned off."""
    result = MCPConnector(spec_for("listing")).sync(interactive=False)

    assert not result.errors
    assert result.added == 3


def test_the_allow_list_survives_a_round_trip_to_disk():
    from chitragupta.connectors.mcp_source import get_server, upsert_server

    upsert_server(spec_for("listing", id="narrow", allowed_tools=["list_records"]))

    assert get_server("narrow").allowed_tools == ["list_records"]


def test_permits_defaults_to_open_and_narrows_when_set():
    open_spec = spec_for("listing")
    narrow = spec_for("listing", allowed_tools=["list_records"])

    assert open_spec.permits("anything")
    assert narrow.permits("list_records")
    assert not narrow.permits("delete_record")
