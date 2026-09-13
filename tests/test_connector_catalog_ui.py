"""The connector catalog's render paths, executed rather than parsed.

`node --check` passes on a temporal-dead-zone `ReferenceError`, and that is
exactly what once blanked the whole Models drawer. Source-order assertions miss
the detached-container bug. So these run the real functions through
`tests/js/connector_catalog.mjs` and read what actually landed on screen.

The backend half of this feature is covered in `tests/connectors/`; what is new
here is the surface a user actually touches, which had no coverage at all and is
the reason every MCP connector built so far was invisible.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "lodestone" / "web" / "app.js"
HARNESS = ROOT / "tests" / "js" / "connector_catalog.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is needed to execute the frontend")

CATALOG = {
    "available": [
        {"id": "slack", "name": "Slack", "notes": "A bot only sees channels it "
         "has been invited to.", "first_party": True, "added": False,
         "needs_env": [{"name": "SLACK_BOT_TOKEN", "help": "A Slack bot token."}]},
        {"id": "github", "name": "GitHub", "notes": "", "first_party": True,
         "added": True, "needs_env": []},
    ],
    "blocked": [
        {"id": "linkedin", "name": "LinkedIn",
         "reason": "LinkedIn does not allow apps to read your feed, connections "
                   "or messages — its terms ban automated access, and the tools "
                   "that claim to do it can get your account banned."},
    ],
}


def run(scenario: dict) -> dict:
    proc = subprocess.run(
        ["node", str(HARNESS), str(APP_JS)],
        input=json.dumps(scenario), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"harness crashed:\n{proc.stderr}"
    return json.loads(proc.stdout)


# ── the harness must be able to fail ───────────────────────────────────────


def test_the_harness_reports_a_thrown_error():
    """A harness that cannot fail proves nothing. This checks it notices when
    the render path throws, which is the whole reason it exists."""
    out = run({"mode": "catalog",
               "api": {"/api/connectors/catalog": {"__throw": "boom"}}})

    # The path catches its own fetch failure and says so on screen rather than
    # dying — so the evidence is in the text it wrote, not in a crash.
    assert out["ok"]
    assert any("boom" in w["text"] for w in out["textWrites"]), out["textWrites"]


# ── the browser ────────────────────────────────────────────────────────────


def test_the_catalog_renders_every_available_connector():
    out = run({"mode": "catalog", "api": {"/api/connectors/catalog": CATALOG}})

    assert out["ok"], out["error"]
    assert "Slack" in out["catalogHtml"]
    assert "GitHub" in out["catalogHtml"]


def test_an_already_added_connector_cannot_be_added_twice():
    out = run({"mode": "catalog", "api": {"/api/connectors/catalog": CATALOG}})

    by_id = {b["id"]: b for b in out["addButtons"]}
    assert by_id["github"]["disabled"] is True
    assert by_id["slack"]["disabled"] is False


def test_a_blocked_source_is_shown_with_its_reason():
    """Omitting LinkedIn teaches the user the app is missing a feature. The
    honest version says no app can do it, where the control would have been."""
    out = run({"mode": "catalog", "api": {"/api/connectors/catalog": CATALOG}})

    assert "LinkedIn" in out["catalogHtml"]
    assert "banned" in out["catalogHtml"]
    assert "unavailable" in out["catalogHtml"]


def test_a_blocked_source_has_no_add_button():
    out = run({"mode": "catalog", "api": {"/api/connectors/catalog": CATALOG}})

    assert "linkedin" not in [b["id"] for b in out["addButtons"]]


def test_the_acronym_never_reaches_the_user():
    """To the user these are connectors. "MCP" is an internal, and CLAUDE.md's
    rule against surfacing one applies to a protocol name as much as to a
    stack trace."""
    out = run({"mode": "catalog", "api": {"/api/connectors/catalog": CATALOG}})

    assert "MCP" not in out["catalogHtml"]
    assert "mcp" not in out["catalogHtml"].lower().replace("data-cx", "")


# ── the permission step ────────────────────────────────────────────────────

PERMS = {
    "id": "slack", "name": "Slack", "available": True, "reason": "",
    "first_party": True, "notes": "", "can_sync": True,
    "needs_env": [{"name": "SLACK_BOT_TOKEN", "help": "A Slack bot token."}],
    "reads": ["list_channels", "read_messages"],
    "writes": ["post_message"],
}


def test_reads_and_writes_are_shown_before_adding():
    """Consent to something nobody has been shown is not consent."""
    out = run({"mode": "permissions", "entry": "slack",
               "api": {"/api/connectors/catalog/slack/permissions": PERMS}})

    assert out["ok"], out["error"]
    assert "list_channels" in out["permHtml"]
    assert "post_message" in out["permHtml"]
    assert "Read" in out["permHtml"] and "Change" in out["permHtml"]


def test_a_connector_that_can_change_things_says_it_will_ask_first():
    out = run({"mode": "permissions", "entry": "slack",
               "api": {"/api/connectors/catalog/slack/permissions": PERMS}})

    assert "asks you first" in out["permHtml"]


def test_a_read_only_connector_says_so_plainly():
    read_only = {**PERMS, "writes": []}
    out = run({"mode": "permissions", "entry": "slack",
               "api": {"/api/connectors/catalog/slack/permissions": read_only}})

    assert "read-only" in out["permHtml"]
    assert "asks you first" not in out["permHtml"]


def test_required_credentials_are_asked_for_with_an_explanation():
    out = run({"mode": "permissions", "entry": "slack",
               "api": {"/api/connectors/catalog/slack/permissions": PERMS}})

    assert "SLACK_BOT_TOKEN" in out["permHtml"]
    assert "A Slack bot token." in out["permHtml"]
    assert 'type="password"' in out["permHtml"]


def test_a_search_only_connector_explains_why_it_will_not_sync():
    """The honest failure mode: it can answer questions but cannot enumerate,
    and saying nothing would look like a connector that silently does nothing."""
    search_only = {**PERMS, "can_sync": False}
    out = run({"mode": "permissions", "entry": "slack",
               "api": {"/api/connectors/catalog/slack/permissions": search_only}})

    assert "searched" in out["permHtml"] and "on demand" in out["permHtml"]


def test_an_unavailable_connector_shows_its_reason_not_a_form():
    unavailable = {"id": "x", "available": False,
                   "reason": "That connector needs a runtime that is not installed."}
    out = run({"mode": "permissions", "entry": "x",
               "api": {"/api/connectors/catalog/x/permissions": unavailable}})

    assert "is not installed" in out["permHtml"]
    assert "Add connector" not in out["permHtml"]


def test_a_reason_is_escaped_before_it_reaches_the_page():
    """Reasons come from a server's own output, so they are untrusted text.

    Every other `innerHTML` path in this file goes through `esc()`; this is the
    one that carries a third party's words, and it must not be the exception.
    """
    out = run({"mode": "permissions", "entry": "x",
               "api": {"/api/connectors/catalog/x/permissions": {
                   "id": "x", "available": False,
                   "reason": "<img src=x onerror=alert(1)> broke"}}})

    assert "<img" not in out["permHtml"]
    assert "&lt;img" in out["permHtml"]
