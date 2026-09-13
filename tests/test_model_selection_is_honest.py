"""The model the composer shows must be the model the turn uses.

These drifted apart in the shipped app, and the symptom was the agent appearing
to lie about itself: the pill read **xAI**, and asked what it was running on the
agent answered **Claude Code**. It was telling the truth — that really was the
provider serving the turn.

The cause was three readers and one writer. Picking a provider in the composer
set `activePickerProvider`, relabelled the pill, and POSTed the agent's binding.
It did not touch `#provider`, a hidden `<select>` in the Models drawer — and
`streamTurn` sends `$("#provider").value`. On the server the request wins over
the agent binding (`run_turn`), so the stale drawer value overrode the fresh
pick on every turn.

Neither half is wrong when read alone, which is why reading the source did not
find it. Running the pick and then reading what the request would carry does.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "lodestone" / "web" / "app.js"
HARNESS = ROOT / "tests" / "js" / "model_selection.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is needed to execute the frontend")

PROVIDERS = [
    {"id": "claude-code", "label": "Claude Code", "connected": True},
    {"id": "xai", "label": "xAI", "connected": True},
    {"id": "openai", "label": "OpenAI", "connected": True},
]

#: The state the bug was reproduced from: a drawer still holding Claude Code.
STALE = {"lodestone_provider": "claude-code", "lodestone_model": "claude-code"}


def run(scenario: dict) -> dict:
    proc = subprocess.run(["node", str(HARNESS), str(APP_JS)],
                          input=json.dumps(scenario), capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, f"harness crashed:\n{proc.stderr}"
    return json.loads(proc.stdout)


# ── the reported bug ───────────────────────────────────────────────────────


def test_picking_a_provider_changes_what_the_turn_sends():
    """The exact reported failure: pill says xAI, turn runs on Claude Code."""
    out = run({"mode": "pick", "pick": "xai", "providers": PROVIDERS,
               "storage": STALE})

    assert out["ok"], out["error"]
    assert out["requestProvider"] == "xai", (
        f"the composer would still send {out['requestProvider']!r} — the agent "
        "would report that provider, correctly, and look like it was lying")


@pytest.mark.parametrize("pick", ["xai", "openai", "claude-code"])
def test_every_provider_reaches_the_request(pick):
    out = run({"mode": "pick", "pick": pick, "providers": PROVIDERS,
               "storage": STALE})

    assert out["requestProvider"] == pick


def test_the_choice_survives_a_reload():
    """`localStorage` is what the next launch reads. A pick that only lived in
    a JS variable was gone the moment the window reloaded."""
    out = run({"mode": "pick", "pick": "openai", "providers": PROVIDERS,
               "storage": STALE})

    assert out["savedProvider"] == "openai"


def test_the_hidden_select_and_the_pill_agree():
    """One writer, three readers — the shape the drift came from."""
    out = run({"mode": "pick", "pick": "xai", "providers": PROVIDERS,
               "storage": STALE})

    assert out["selectValue"] == out["requestProvider"] == out["savedProvider"]


def test_the_agent_binding_is_still_saved():
    """The fix must not replace the binding POST — an agent keeps its own
    model, and that is what the picker was doing right."""
    out = run({"mode": "pick", "pick": "xai", "providers": PROVIDERS,
               "storage": STALE})

    posts = [p for p in out["posts"] if "/model" in p["path"]]
    assert posts, "the agent's model binding was no longer saved"
    assert json.loads(posts[0]["body"])["provider"] == "xai"


# ── "Auto", and the model half ─────────────────────────────────────────────


def test_choosing_a_provider_clears_a_stale_model_id():
    """Picking xAI while `lodestone_model` still held `claude-code` would send
    xAI *with Claude's model id*, which is a 400 at best."""
    out = run({"mode": "pick", "pick": "xai", "providers": PROVIDERS,
               "storage": STALE})

    assert out["requestModel"] is None, (
        f"a model id from another provider survived: {out['requestModel']!r}")


def test_an_explicit_model_is_sent():
    out = run({"mode": "direct", "pick": "xai", "model": "grok-4",
               "storage": STALE})

    assert out["requestProvider"] == "xai"
    assert out["requestModel"] == "grok-4"


def test_auto_means_no_model_id_at_all():
    """Not an empty string — `run_turn` reads a falsy model as "decide for me",
    and an empty string that reaches a provider is a different request."""
    out = run({"mode": "direct", "pick": "openai", "model": None,
               "storage": STALE})

    assert out["savedModel"] is None
    assert out["requestModel"] is None


def test_a_provider_missing_from_the_catalog_still_takes():
    """A `<select>` silently keeps its old value when assigned one it has no
    option for — the same class of drift, one level down."""
    out = run({"mode": "direct", "pick": "some-new-provider", "model": None,
               "storage": STALE})

    assert out["selectValue"] == "some-new-provider"
    assert out["requestProvider"] == "some-new-provider"
