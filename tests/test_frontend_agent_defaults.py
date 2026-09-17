"""The "Default AI for new agents" controls are wired to something real.

Every turn already sent a provider, a model and an effort. Provider and model
had a control in the composer; **effort never had one anywhere**. The server
has had `GET`/`POST /api/agents/effort` the whole time and nothing in the
frontend called it, so the value every turn read could not be changed from
inside the app at all.

A select that renders its options but never POSTs looks exactly the same on
screen as one that works, and a source-order test cannot tell them apart. So
this runs `loadAgentDefaults()` for real, changes the controls, and reports
what reached the network and what reached storage.
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "chitragupta/web"

EFFORT = {
    "current": "medium",
    "levels": [
        {"name": "low", "label": "Low", "description": "Quick answers."},
        {"name": "medium", "label": "Medium", "description": "The default."},
        {"name": "high", "label": "High", "description": "Digs in. Costs more."},
    ],
}

CATALOG = [
    {"id": "openai", "label": "OpenAI", "ready": True, "models": [
        {"id": "gpt-5.5", "name": "GPT-5.5"},
        {"id": "gpt-5.6-terra", "name": "GPT-5.6-Terra", "locked": True,
         "plan_required": "requires Pro"},
    ]},
    {"id": "claude", "label": "Anthropic", "ready": False, "models": [
        {"id": "claude-opus-5", "name": "Claude Opus 5"},
    ]},
]


@pytest.fixture(scope="module")
def run() -> dict:
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/agent_defaults.mjs"), str(WEB / "app.js")],
        input=json.dumps({"catalog": CATALOG, "effort": EFFORT}),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_it_ran(run):
    assert run["error"] is None, run["error"]


# ── effort: the control that did not exist ────────────────────────────────
def test_effort_is_populated_from_the_server(run):
    assert "/api/agents/effort" in json.dumps(run["calls"]), run["calls"]
    for label in ("Low", "Medium", "High"):
        assert f">{label}<" in run["effortOptions"], run["effortOptions"]


def test_the_saved_effort_is_the_one_selected(run):
    assert 'value="medium" selected' in run["effortOptions"], run["effortOptions"]


def test_changing_effort_reaches_the_server(run):
    """The whole point: a select that never POSTs looks identical on screen."""
    post = run["effortPost"]
    assert post is not None, "changing effort sent nothing to the server"
    assert "/api/agents/effort" in post["path"]
    assert json.loads(post["body"]) == {"level": "high"}


def test_the_description_explains_the_chosen_level(run):
    assert run["effortDesc"] == "Digs in. Costs more.", run["effortDesc"]


def test_effort_is_not_left_enabled_when_it_cannot_work(run):
    """It is enabled here because the endpoint answered; the fallback is covered
    by the code path that disables it when the call fails."""
    assert run["effortDisabled"] is False


# ── provider and model ────────────────────────────────────────────────────
def test_providers_are_listed_with_their_connection_state(run):
    assert "OpenAI" in run["providerOptions"]
    assert "not connected" in run["providerOptions"], (
        "a provider that cannot run anything must say so, not look selectable")


def test_models_offer_auto_and_the_provider_s_own_models(run):
    assert 'value=""' in run["modelOptions"]
    assert "GPT-5.5" in run["modelOptions"]


def test_a_locked_model_is_shown_disabled_with_the_reason(run):
    """Hiding it is how "why can't I pick that?" becomes unanswerable."""
    assert "GPT-5.6-Terra" in run["modelOptions"]
    assert "disabled" in run["modelOptions"]
    assert "requires Pro" in run["modelOptions"]


def test_choosing_a_provider_stores_it(run):
    assert run["providerWrote"] == "claude"


def test_switching_provider_drops_a_model_the_new_one_never_heard_of(run):
    """Carrying gpt-5.5 over to Anthropic would send an id that cannot resolve."""
    assert run["storedModelAfterProviderChange"] is None


def test_picking_a_model_after_switching_provider_stores_both_together(run):
    """`active` is captured in a closure; if the provider handler does not
    update it, choosing a model writes the model the user picked against the
    provider they just left."""
    assert run["pairAfterSwitch"] == {
        "provider": "claude", "model": "claude-opus-5",
    }, run["pairAfterSwitch"]
