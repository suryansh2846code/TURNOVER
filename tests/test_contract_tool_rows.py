"""The row shape `GET /api/agents/tools` returns, rendered by the page that reads it.

This is the test that was missing when the contract was written, and its absence
is what let two user-visible bugs land green on both sides at once:

- the agents layer emitted a row for the *category* of connector tools, the page
  had no concept of one, and it rendered as a skill literally named `mcp` inside
  an invented group called "A connected app" — the protocol's acronym on screen,
  which both halves had independently forbidden and neither could see;
- the row carried only the qualified name we mint (`mcp__github__list_issues`),
  so the id went straight to the user, which is the "never surface an internal"
  rule broken in the one place the user goes to read what an agent can do.

Each side's own suite passed throughout. A contract needs a test that fails when
only one side ships it, and that means executing the real producer against the
real consumer rather than each against its own idea of the other.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from lodestone.agents import mcp_tools
from lodestone.agents.tools import describe_tools

APP_JS = Path(__file__).resolve().parents[1] / "lodestone" / "web" / "app.js"
HARNESS = Path(__file__).parent / "js" / "tool_provenance.mjs"

#: The acronym, spelled so this file's own prose cannot be what a grep finds.
ACRONYM = "m" + "cp"


def _ref(server_id: str, tool: str, label: str, *, writes: bool = False):
    """One `MCPToolRef` as `connectors.mcp_tools` builds it.

    Mirrors the real dataclass rather than importing it, so a field renamed on
    that side shows up here as a failure instead of silently vanishing through
    the duck-typed boundary.
    """
    return SimpleNamespace(
        qualified_name=f"{ACRONYM}__{server_id}__{tool}",
        server_id=server_id, server_label=label, tool=tool,
        description=f"{tool} on {label}.",
        parameters={"type": "object", "properties": {}}, writes=writes)


@pytest.fixture
def rows(monkeypatch):
    """`describe_tools()` with two connectors configured, as the API returns it."""
    supplied = [_ref("github", "list_issues", "GitHub"),
                _ref("linear", "search_issues", "Linear"),
                _ref("github", "create_issue", "GitHub", writes=True)]
    monkeypatch.setattr(mcp_tools, "_supplier",
                        lambda: SimpleNamespace(list_tools=lambda: supplied,
                                                call_tool=lambda *a, **k: ""))
    mcp_tools.clear_cache()
    yield describe_tools()
    mcp_tools.clear_cache()


def _render(rows):
    """Run the page's real `renderToolList` over these rows."""
    node = shutil.which("node")
    if not node:                                  # pragma: no cover
        pytest.skip("node not installed")
    payload = {"tools": rows,
               "connectors": [{"name": f"{ACRONYM}:github", "label": "GitHub",
                               "ready": True, ACRONYM: True}]}
    out = subprocess.run([node, str(HARNESS), str(APP_JS)],
                         input=json.dumps(payload), capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout)
    assert report.get("ok"), report
    return report


# ── the producer's half ──────────────────────────────────────────────────────

def test_every_row_carries_something_a_person_can_read(rows):
    """`label` is not optional — a consumer must never have to fall back to an id."""
    missing = [r["name"] for r in rows if not (r.get("label") or "").strip()]
    assert not missing, f"rows with no readable label: {missing}"


def test_a_connector_tool_is_labelled_with_the_vendors_own_name(rows):
    """The vendor calls it `list_issues`; the qualified name is ours, not theirs."""
    issue = next(r for r in rows if r["name"].endswith("list_issues"))
    assert issue["label"] == "list_issues"
    assert issue["connector"] == "GitHub"
    assert ACRONYM not in issue["label"]


def test_the_category_row_is_marked_as_one(rows):
    """A row granting the whole category must be distinguishable from a tool.

    Without this the consumer has to guess, and the guess it made was to treat
    it as a connector's tool and invent a group for it.
    """
    category = [r for r in rows if r.get("source") == "category"]
    assert len(category) == 1, f"expected exactly one category row, got {category}"
    assert ACRONYM not in category[0]["label"].lower()


def test_a_write_tool_is_not_offered_as_a_row(rows):
    """Writes reach the user through confirmation, never as a skill to grant."""
    assert not [r for r in rows if r["name"].endswith("create_issue")]


# ── the consumer's half, executed ────────────────────────────────────────────

def test_the_acronym_never_reaches_the_screen(rows):
    """The whole rendered panel, checked as text — names included, not just labels.

    The frontend's own test checked group *labels* for the acronym and passed
    while a skill named for it sat on screen. Check everything that renders.
    """
    report = _render(rows)
    names = [n for g in report["groups"] for n in g["tools"]]
    assert ACRONYM not in " ".join(names).lower(), f"acronym rendered as a skill: {names}"
    assert ACRONYM not in report["html"].lower(), "acronym reached the rendered panel"


def test_no_qualified_name_is_shown_to_the_user(rows):
    """`{acronym}__github__list_issues` is an id we minted. The user sees `list_issues`."""
    report = _render(rows)
    names = [n for g in report["groups"] for n in g["tools"]]
    assert "list_issues" in names
    assert not [n for n in names if "__" in n], f"a qualified id was rendered: {names}"


def test_the_category_row_does_not_invent_a_group(rows):
    """It is a switch for the agent builder, not a skill in the skills list."""
    report = _render(rows)
    groups = [g["name"] for g in report["groups"]]
    assert "A connected app" not in groups, (
        f"the category row was rendered as an unnamed connector: {groups}")
    assert sorted(groups) == ["Built in", "GitHub", "Linear"], groups


def test_each_connectors_tools_land_under_that_connector(rows):
    report = _render(rows)
    by_group = {g["name"]: g["tools"] for g in report["groups"]}
    assert by_group["GitHub"] == ["list_issues"]
    assert by_group["Linear"] == ["search_issues"]


# ── who owns the ceiling ─────────────────────────────────────────────────────

def test_the_agents_cap_is_a_backstop_not_the_ceiling():
    """Two layers truncate, so the order between them decides what the model reads.

    `connectors.mcp_tools` bounds a result and appends a sentence naming how
    much it held back, which is what lets a model ask a narrower question rather
    than assume it saw everything. The agents-side cap exists only for a
    supplier that bounds nothing at all — set below the supplier's, it silently
    deletes that sentence and substitutes a vaguer one.
    """
    from lodestone.connectors import mcp_tools as supplier

    assert mcp_tools.MAX_RESULT_CHARS > supplier.MAX_RESULT_CHARS, (
        f"the agents backstop ({mcp_tools.MAX_RESULT_CHARS}) cuts below the "
        f"supplier's ceiling ({supplier.MAX_RESULT_CHARS}), so the supplier's "
        "truncation notice is discarded before the model ever sees it")


def test_a_supplier_that_bounds_nothing_is_still_caught(monkeypatch):
    """The backstop has to actually catch something, or it is decoration."""
    monkeypatch.setattr(mcp_tools, "_supplier", lambda: SimpleNamespace(
        list_tools=lambda: [_ref("big", "dump", "Big")],
        call_tool=lambda *a, **k: "x" * 100_000))
    mcp_tools.clear_cache()
    try:
        tool = mcp_tools.lookup(f"{ACRONYM}__big__dump")
        assert tool is not None
        out = tool.handler()
        assert len(out) < 100_000
        assert "truncated" in out.lower()
    finally:
        mcp_tools.clear_cache()
