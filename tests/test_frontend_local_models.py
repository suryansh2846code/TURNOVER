"""Ollama can be reached from the Models screen.

Its box rendered with no account card, no sign-in and no API key field —
nothing to press at all — because all three of those cards are about collecting
a credential and a local server has none. Meanwhile every one of its models
carried the label "Connect in Models", which is read by somebody already
standing in Models, pointing at a button that does not and should not exist.

The backend was never the problem: `discover_ollama_models` already asks the
local server what is installed, with real sizes, and marks the rest "Pull
required". Only the screen was missing.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "chitragupta/web"
MODELS_JS = (WEB / "models.js").read_text()


def _catalog(tmp_path: Path, **ollama) -> Path:
    base = {
        "id": "ollama", "label": "Ollama (Local)", "locality": "local",
        "ready": False, "reason": "Ollama not running on localhost:11434",
        "key_url": "https://ollama.com", "key_env": "",
        "capabilities": {"provider_id": "ollama", "api_key_supported": False,
                         "oauth_supported": False, "browser_login_supported": False,
                         "device_login_supported": False,
                         "model_discovery_supported": True},
        "models": [{"id": "llama3.2", "name": "Llama 3.2", "locked": True,
                    "plan_required": "Pull required"}],
    }
    base.update(ollama)
    # A cloud provider and a local CLI-account provider alongside, because the
    # card is chosen by capability and both must keep the cards they had.
    others = [
        {"id": "openai", "label": "OpenAI", "locality": "cloud", "ready": False,
         "capabilities": {"provider_id": "openai", "api_key_supported": True,
                          "oauth_supported": True, "model_discovery_supported": True},
         "models": []},
        {"id": "claude-code", "label": "Claude Code CLI", "locality": "cloud",
         "ready": False,
         "capabilities": {"provider_id": "claude-code", "api_key_supported": False,
                          "oauth_supported": False, "model_discovery_supported": False},
         "models": []},
    ]
    p = tmp_path / "catalog.json"
    p.write_text(json.dumps([base, *others]))
    return p


def render(provider: str, path: Path) -> str:
    proc = subprocess.run(
        ["node", str(ROOT / "tests/js/local_provider_card.mjs"), provider, str(path)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return proc.stdout


# ── the section ───────────────────────────────────────────────────────────
def test_ollama_has_a_section_of_its_own():
    """It was buried under "Other ways to run models" beside two cloud API-key
    providers, which is neither where somebody looks for it nor what it is."""
    groups = MODELS_JS.split("const GROUPS = [", 1)[1].split("];", 1)[0]
    local = groups.split('id: "local"', 1)[1].split("},", 1)[0]
    assert '"ollama"' in local
    other = groups.split('id: "other"', 1)[1].split("},", 1)[0]
    assert '"ollama"' not in other, "Ollama is still in the catch-all group too"


# ── the card ──────────────────────────────────────────────────────────────
def test_a_stopped_server_says_so_and_offers_the_one_thing_that_helps(tmp_path):
    html = render("ollama", _catalog(tmp_path))
    assert "local-server" in html
    assert "Not running" in html
    assert "Ollama not running on localhost:11434" in html
    assert "Check again" in html
    assert "ollama.com" in html


def test_a_stopped_server_is_not_offered_a_sign_in(tmp_path):
    """There is no account to sign into. A button here would do nothing."""
    html = render("ollama", _catalog(tmp_path))
    assert "ts-btn-signin" not in html
    assert "apiKeyInput" not in html


def test_a_running_server_reports_what_is_installed(tmp_path):
    path = _catalog(tmp_path, ready=True, reason="", models=[
        {"id": "llama3.2", "name": "Llama 3.2", "locked": False},
        {"id": "qwen2.5:3b", "name": "Qwen 2.5", "locked": False},
        {"id": "llama3.3:70b", "name": "Llama 3.3", "locked": True,
         "plan_required": "Pull required"}])
    html = render("ollama", path)
    assert "Running" in html
    assert "2 models installed" in html, html[:300]
    assert "Get Ollama" not in html, "still telling a running install to install"


def test_one_model_is_not_1_models(tmp_path):
    path = _catalog(tmp_path, ready=True, reason="",
                    models=[{"id": "llama3.2", "name": "Llama 3.2", "locked": False}])
    assert "1 model installed" in render("ollama", path)


# ── the card is chosen by capability, not by name ─────────────────────────
def test_the_local_card_is_not_a_provider_id_branch():
    """"Derive UI from capabilities, never from a `providerId === "x"` chain.""" ""
    src = (WEB / "providers.js").read_text()
    block = src.split("const isLocalServer", 1)[1].split(";", 1)[0]
    assert "ollama" not in block.lower(), block


@pytest.mark.parametrize("provider", ["openai", "claude-code"])
def test_no_other_provider_is_given_the_local_card(provider, tmp_path):
    """`claude-code` is the near miss: no API key and no OAuth either, so only
    `locality` and `model_discovery_supported` keep it out. `cursor` is the
    other — local, but it takes a key."""
    assert "local-server" not in render(provider, _catalog(tmp_path))


def test_the_local_card_needs_every_one_of_its_conditions(tmp_path):
    """Each clause is load-bearing: drop any one and a provider that collects a
    credential starts being told it is a local server."""
    for change in ({"locality": "cloud"},
                   {"capabilities": {"provider_id": "ollama", "api_key_supported": True,
                                     "oauth_supported": False, "model_discovery_supported": True}},
                   {"capabilities": {"provider_id": "ollama", "api_key_supported": False,
                                     "oauth_supported": False, "model_discovery_supported": False}}):
        html = render("ollama", _catalog(tmp_path, **change))
        assert "local-server" not in html, f"still a local server with {change}"


# ── the label that pointed nowhere ────────────────────────────────────────
def test_a_locked_model_no_longer_says_connect_in_models():
    """Read on the Models screen itself, about a provider with no connect step."""
    assert '"Connect in Models"' not in MODELS_JS.split("function lockReason", 1)[0] \
        .split("plan_required:", 1)[-1][:400]


def test_the_reason_a_model_is_locked_is_about_what_you_would_do():
    # Split on the name, not the signature — the claim is about what the
    # function returns, and pinning the parameter's spelling made a
    # rename look like a broken feature.
    fn = MODELS_JS.split("function lockReason(", 1)[1].split("\n}", 1)[0]
    assert "Not running" in fn and "Connect first" in fn
