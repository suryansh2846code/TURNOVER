"""A model cannot call a tool correctly if it is never told what the tool takes.

From a real machine. A user asked an agent to delete a Notion page. Notion's
connector has no delete tool at all — 44 of them, none that trash a page — so
the honest answer was "I can't". Instead the agent reached for
`notion-update-page` with `in_trash: true`, which is a real field in Notion's
WEB API and is not a parameter of this tool, and failed three times.

It was not being careless. This is everything it had been told about that tool:

    - server="notion" tool="notion-update-page" — Notion: ## Overview

The name, and a markdown heading — because the description was cut at its first
line and Notion writes its tool docs starting with one. No arguments at all. So
it filled them in from what it remembered of Notion's public API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from lodestone.agents import mcp_tools, prompt
from lodestone.agents.mcp_tools import SENTINEL
from lodestone.agents.prompt import (
    MAX_ARGS_SHOWN,
    _argument_names,
    _connector_actions,
    _first_sentence,
)


@dataclass
class WriteRef:
    server_id: str
    server_label: str
    tool: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    writes: bool = True


#: Notion's real description and real schema, as this machine reports them.
UPDATE_PAGE = WriteRef(
    "notion", "Notion", "notion-update-page",
    "## Overview\n\nUpdate a Notion page's properties or content.\n\n"
    "## Properties\n\nNotion page properties are a JSON map.",
    {"type": "object",
     "properties": {k: {"type": "string"} for k in
                    ("page_id", "command", "properties", "content",
                     "content_updates", "cover", "icon", "position")},
     "required": ["page_id", "command"]},
)


@pytest.fixture
def notion(monkeypatch):
    monkeypatch.setattr(prompt, "_connector_actions", prompt._connector_actions)
    monkeypatch.setattr(
        "lodestone.connectors.mcp_tools.write_tools", lambda: [UPDATE_PAGE],
        raising=False)
    monkeypatch.setattr(mcp_tools, "_supplier",
                        lambda: SimpleNamespace(list_tools=lambda: [UPDATE_PAGE],
                                                call_tool=lambda *a, **k: "ok",
                                                write_tools=lambda: [UPDATE_PAGE]))
    mcp_tools.clear_cache()
    return _connector_actions([SENTINEL])


# ── the description ──────────────────────────────────────────────────────
def test_a_markdown_heading_is_not_a_description():
    """"## Overview" looks like a description and carries nothing."""
    assert _first_sentence(UPDATE_PAGE.description) == \
        "Update a Notion page's properties or content."


def test_headings_rules_and_fences_are_all_skipped():
    assert _first_sentence("# Title\n---\n```\nThe real sentence here.") == \
        "The real sentence here."


def test_a_description_that_is_only_structure_yields_nothing():
    """Better to say nothing than to pass a heading off as prose."""
    assert _first_sentence("## Overview\n\n### Details") == ""
    assert _first_sentence("") == ""


def test_a_long_description_is_cut_to_one_line():
    out = _first_sentence("x" * 900)
    assert len(out) <= prompt.MAX_DESCRIPTION_CHARS + 1


# ── the arguments ────────────────────────────────────────────────────────
def test_the_arguments_are_named():
    """The whole reason `in_trash` was invented."""
    takes = _argument_names(UPDATE_PAGE)
    for real in ("page_id", "command", "properties", "content"):
        assert real in takes
    assert "in_trash" not in takes, "the schema does not have it, so neither should this"


def test_required_arguments_are_starred_and_come_first():
    takes = _argument_names(UPDATE_PAGE)
    assert takes.startswith("command*, page_id*"), takes


def test_a_tool_with_many_arguments_does_not_become_the_prompt():
    many = WriteRef("x", "X", "t", "does a thing.",
                    {"properties": {f"arg{i}": {} for i in range(40)},
                     "required": []})
    takes = _argument_names(many)
    assert takes.count(",") < MAX_ARGS_SHOWN + 2
    assert "more" in takes, "it must say that it held some back"


def test_a_tool_with_no_schema_says_nothing_rather_than_guessing():
    assert _argument_names(WriteRef("x", "X", "t", "d", {})) == ""
    assert _argument_names(SimpleNamespace(parameters=None)) == ""


# ── the block a model actually reads ─────────────────────────────────────
def test_the_model_is_told_the_name_the_purpose_and_the_arguments(notion):
    assert 'tool="notion-update-page"' in notion
    assert "Update a Notion page's properties or content." in notion
    assert "takes:" in notion and "page_id*" in notion
    assert "## Overview" not in notion, "the heading is still being passed off as prose"


def test_the_model_is_told_not_to_invent_an_argument(notion):
    """The instruction that turns "I'll guess" into "it can't do that"."""
    assert "ONLY the arguments listed" in notion
    assert "cannot do it rather than inventing" in notion


def test_a_tool_that_does_not_exist_is_not_described(notion):
    """Notion's connector has no delete. The prompt must not imply one."""
    for invented in ("delete-page", "trash-page", "archive-page", "in_trash"):
        assert invented not in notion


def test_an_agent_without_connector_access_is_told_none_of_this(notion):
    assert _connector_actions([]) == ""
    assert _connector_actions(["search_brain"]) == ""
