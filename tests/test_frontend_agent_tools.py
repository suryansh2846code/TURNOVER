"""What one agent may use, and why it cannot use the rest.

A user connected Notion, asked their agent about it, and was told it was still
syncing. It wasn't — the agent simply had no connector access, and no screen
anywhere would have shown them that. This is that screen, and these are the
properties that make it answer the question instead of restating it.

Everything here runs the real render and reads what landed. `node --check`
passes on a temporal-dead-zone ReferenceError, which is how a panel once
rendered blank while every test passed, and the interesting facts — which
group a tool landed in, whether a row is a switch or a reason, what the switch
sent — are all properties of the produced DOM.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"

BUILTIN = [
    {"name": "search_brain", "label": "search_brain", "description": "Search your brain",
     "source": "builtin", "connector": ""},
    {"name": "remember", "label": "remember", "description": "Remember something",
     "source": "builtin", "connector": ""},
]
CATEGORY = {"name": "mcp", "label": "Everything my connectors can read",
            "description": "Stays correct as connectors are added or removed.",
            "source": "category", "connector": ""}
NOTION_TOOL = {"name": "notion__search", "label": "Search Notion",
               "description": "Search pages", "source": "mcp", "connector": "Notion"}

READY = {"name": "notion", "label": "Notion", "ready": True, "reason": "", "mcp": True}
DOWN = {"name": "linear", "label": "Linear", "ready": False,
        "reason": "Linear needs signing in", "mcp": True}


def run(agent_tools, tools, connectors, **kw) -> dict:
    payload = {
        "agent": {"id": "chotu", "name": "chotu", "tools": agent_tools},
        "tools": tools, "connectors": connectors, **kw,
    }
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/agent_tools.mjs"), str(WEB / "app.js")],
        input=json.dumps(payload), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2500:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def full() -> dict:
    return run(["search_brain"], [*BUILTIN, CATEGORY, NOTION_TOOL], [READY, DOWN],
               toggle="mcp")


# ── grouping: where a tool comes from ─────────────────────────────────────
def test_tools_are_grouped_by_where_they_come_from(full):
    kinds = {g["name"]: g["kind"] for g in full["groups"]}
    assert kinds["Built in"] == "builtin"
    assert kinds["Notion"] == "connector"
    assert kinds["Your connectors"] == "category"


def test_a_connector_tool_is_named_after_its_connector(full):
    """"search" and "search_2" are indistinguishable; "Search Notion" is not."""
    notion = next(g for g in full["groups"] if g["name"] == "Notion")
    assert notion["tools"] == ["notion__search"]
    assert "Search Notion" in full["html"]


def test_connectors_come_before_the_built_ins(full):
    """The screen exists because of connectors. Built-ins never needed
    explaining, so they do not go first."""
    names = [g["name"] for g in full["groups"]]
    assert names.index("Your connectors") < names.index("Built in")
    assert names.index("Notion") < names.index("Built in")


def test_the_category_is_its_own_group(full):
    """It grants everything the connectors can read, so filing it under one
    connector would misdescribe what the switch does."""
    cat = next(g for g in full["groups"] if g["kind"] == "category")
    assert cat["tools"] == ["mcp"]


def test_the_category_shows_its_label_never_its_stored_value(full):
    assert "Everything my connectors can read" in full["html"]
    assert ">mcp<" not in full["html"], "the protocol's acronym reached the screen"


def test_no_category_row_when_the_user_has_no_connectors():
    """The API omits the row when nothing is behind it; the screen must not
    invent one. A switch that grants nothing reads as a broken app."""
    out = run(["search_brain"], BUILTIN, [])
    assert all(g["kind"] != "category" for g in out["groups"])
    assert "Everything my connectors can read" not in out["html"]


# ── the toggle ────────────────────────────────────────────────────────────
def test_turning_a_tool_on_saves_the_whole_list(full):
    sent = full["toggled"]["sent"]
    assert sent == ["search_brain", "mcp"], sent


def test_it_saves_to_a_relative_path(full):
    """Never a host or port — the desktop app binds a different one per install."""
    assert full["toggled"]["path"] == "/api/agents/chotu/tools"
    assert not full["toggled"]["path"].startswith("http")


def test_the_switch_reports_its_state_to_assistive_tech(full):
    assert full["toggled"]["ariaAfter"] == "true"
    assert 'role="switch"' in full["html"]


def test_turning_one_off_sends_the_list_without_it():
    out = run(["search_brain", "mcp"], [*BUILTIN, CATEGORY, NOTION_TOOL], [READY], toggle="mcp")
    assert out["toggled"]["sent"] == ["search_brain"]


def test_a_failed_save_puts_the_switch_back():
    """A switch left showing a state that was never stored is worse than one
    that refuses: it says the agent can do something it cannot."""
    out = run(["search_brain"], [*BUILTIN, CATEGORY], [READY],
              toggle="mcp", failSave=True)
    assert out["toggled"]["onAfter"] is False
    assert out["toggled"]["ariaAfter"] == "false"
    assert out["agentToolsAfter"] == ["search_brain"]


def test_a_failed_save_explains_itself_in_the_row():
    """Beside the switch that lied, not in a toast that is gone by the time
    the user looks back at it."""
    out = run(["search_brain"], [*BUILTIN, CATEGORY], [READY],
              toggle="mcp", failSave=True)
    assert "Couldn't save" in out["rowError"], out["rowError"]


# ── what cannot be switched ───────────────────────────────────────────────
def test_an_unreachable_connector_states_the_reason(full):
    """Not a disabled toggle with no explanation, and the reason is the
    connector's own — written by the layer that failed."""
    assert "Linear needs signing in" in full["html"]


def test_an_unreachable_connector_is_listed_at_all(full):
    """Contributing no tools, it would otherwise be absent — and absent reads
    as "Lodestone lost it" rather than "sign in again"."""
    assert any(g["name"] == "Linear" for g in full["groups"])


def test_a_blocked_group_shows_the_reason_where_its_rows_would_be(full):
    """A connector that cannot answer contributes no tools, so its card would
    be an empty box under a heading. The reason goes in the card instead, and
    there is no switch anywhere in it — a control that cannot work is not shown
    as a control."""
    linear = full["html"].split("Linear", 1)[1].split("</section>", 1)[0]
    assert "at-toggle" not in linear, linear[:300]
    # Look INSIDE the card, not at the section: the reason is in the group head
    # too, so a slice that includes the head passes whatever the card holds.
    card = linear.split('class="at-card"', 1)[1]
    assert "Linear needs signing in" in card, card[:300]


def test_a_blocked_row_links_to_where_it_is_fixed(full):
    assert "Open Connectors" in full["html"]


def test_that_link_opens_connectors():
    out = run(["search_brain"], [*BUILTIN, CATEGORY], [DOWN], clickFix=True)
    assert out["openedConnectors"] >= 1, "the fix link did not open Connectors"


# ── empty ─────────────────────────────────────────────────────────────────
def test_an_agent_with_no_tools_is_not_a_blank_panel():
    out = run([], [], [])
    assert "no tools yet" in out["html"]
    assert "your brain is read on every" in out["html"], "it must say what still works"
    assert "Open Connectors" in out["html"], "it must offer the first thing worth adding"
