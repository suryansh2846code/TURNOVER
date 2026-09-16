"""A confirmation card a person can actually read, and that cannot crash.

Both of these were seen on a real machine, in the same card.

The card printed the tool's id and every argument raw — `notion-update-page`, a
UUID, `properties {}`, `content_updates []` — which tells nobody what they are
about to approve. And `esc()` assumed a string: a connector tool answers with
whatever shape it likes, `({}).replace` is not a function, so the escaper threw
and the catch above it rendered the TypeError where the real message belonged.
A successful action showed as a red crash.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "lodestone/web"

#: The action from the report, argument for argument.
NOTION_DELETE = {
    "type": "mcp_action",
    "params": {
        "connector": "notion", "server_id": "notion", "tool": "notion-update-page",
        "arguments": {
            "page_id": "3bddf1be-bce9-80d7-a826-c2042f47f837",
            "command": "update_properties",
            "properties": {},
            "content_updates": [],
            "in_trash": True,
        },
    },
}


def _run(action, result):
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/action_card_plain.mjs"), str(WEB / "app.js")],
        input=json.dumps({"action": action, "result": result}),
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def card():
    return _run(NOTION_DELETE, {"ok": True, "detail": {"id": "x", "title": "Q3 plan"}})


def test_it_rendered(card):
    assert card["error"] is None, card["error"]


# ── what a person reads ──────────────────────────────────────────────────
def test_the_title_is_a_sentence_not_a_tool_id(card):
    assert "Update page in Notion" in card["html"]
    assert "notion-update-page" not in card["html"], "the tool id is still on screen"


def test_the_connector_is_not_shouted_in_lower_case(card):
    """"Update page in notion" reads as a typo."""
    assert "in notion<" not in card["html"]


def test_arguments_that_say_nothing_are_not_shown(card):
    """`properties {}` and `content_updates []` are the tool's empty defaults."""
    assert "properties" not in card["html"].lower() or "Properties" not in card["html"]
    assert "content_updates" not in card["html"]
    assert "{}" not in card["html"] and "[]" not in card["html"]


def test_arguments_that_do_say_something_are_still_shown(card):
    """A confirmation the user cannot read is not a confirmation."""
    assert "3bddf1be-bce9-80d7-a826-c2042f47f837" in card["html"], (
        "the page being changed was hidden from the person approving it")
    assert "In trash" in card["html"] and "yes" in card["html"]


def test_argument_names_are_written_as_words(card):
    assert "Page ID" in card["html"]
    assert "page_id" not in card["html"]


# ── the crash ────────────────────────────────────────────────────────────
def test_an_object_result_does_not_become_a_red_typeerror(card):
    """The exact failure: a dict reached esc(), which threw, and the catch
    rendered the TypeError in place of the result."""
    assert "TypeError" not in card["afterConfirm"], card["afterConfirm"]
    assert "ac-ok" in card["afterConfirm"]
    assert "Q3 plan" in card["afterConfirm"]


@pytest.mark.parametrize("detail", [
    {"title": "A page"}, [1, 2, 3], None, "", 42, {"nested": {"deep": True}},
])
def test_no_result_shape_can_crash_the_card(detail):
    out = _run(NOTION_DELETE, {"ok": True, "detail": detail})
    assert out["error"] is None
    assert "TypeError" not in (out["afterConfirm"] or ""), out["afterConfirm"]
    assert "[object Object]" not in (out["afterConfirm"] or "")


def test_a_failure_shows_the_connectors_own_reason():
    out = _run(NOTION_DELETE, {
        "ok": False,
        "error": "Notion refused that: body.in_trash should be defined."})
    assert "ac-err" in out["afterConfirm"]
    assert "in_trash should be defined" in out["afterConfirm"], (
        "the reason the connector gave was dropped")


def test_a_tool_whose_name_is_its_verb_keeps_it():
    """Stripping the connector prefix must not eat a real verb."""
    action = json.loads(json.dumps(NOTION_DELETE))
    action["params"]["tool"] = "search"
    out = _run(action, {"ok": True, "detail": "x"})
    assert "Search in Notion" in out["html"]


# ── the escaper itself ───────────────────────────────────────────────────
def test_the_escaper_survives_every_shape_a_connector_can_answer_with(card):
    """`esc` is what every innerHTML path in the app goes through. A throw here
    does not lose one message — it blanks whatever was being drawn."""
    for shape, outcome in card["escaped"].items():
        assert outcome["ok"], f"esc() threw on a {shape}: {outcome['out']}"
