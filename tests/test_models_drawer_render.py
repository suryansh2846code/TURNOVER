"""The Models drawer must actually render.

`renderProviderConnectBox` once read `caps` five lines before `const caps` was
declared. That is a temporal-dead-zone ReferenceError: the function threw, every
provider card vanished, and the drawer showed nothing but headings. `node
--check` passes on it — TDZ is a runtime error, not a syntax error — and no test
executed the function, so it shipped.

This runs the real function against the real `/api/models/catalog` payload.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
APP_JS = ROOT / "lodestone/web/app.js"
HARNESS = ROOT / "tests/js/render_provider_box.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not installed")


def _render_all() -> dict:
    from lodestone.models.registry import get_model_catalog

    proc = subprocess.run(
        ["node", str(HARNESS), str(APP_JS)],
        input=json.dumps(get_model_catalog()),
        capture_output=True, text=True, timeout=90,
    )
    assert proc.returncode == 0, f"harness failed: {proc.stderr[:400]}"
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def rendered():
    return _render_all()


def test_app_js_is_syntactically_valid():
    proc = subprocess.run(["node", "--check", str(APP_JS)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_every_provider_card_renders_without_throwing(rendered):
    broken = {pid: r["error"] for pid, r in rendered.items() if not r["ok"]}
    assert not broken, f"render threw for: {broken}"


def test_every_provider_renders_visible_content(rendered):
    """A card that renders an empty string is the bug, silently."""
    empty = [pid for pid, r in rendered.items() if r["ok"] and r["length"] < 200]
    assert not empty, f"these providers rendered nothing: {empty}"


# ── the card each provider should get, derived from its capabilities ─────
def test_key_only_providers_get_no_account_or_signin_card(rendered):
    from lodestone.models.capabilities import get_capabilities

    for pid, r in rendered.items():
        caps = get_capabilities(pid)
        if caps and caps.api_key_only:
            assert not r["hasAccountCard"], f"{pid} offered an account card"
            assert not r["hasSigninButton"], f"{pid} offered a sign-in it cannot honour"
            assert r["hasApiKeyCard"], f"{pid} is key-only but has no key field"


def test_signin_button_appears_only_where_a_sign_in_exists(rendered):
    from lodestone.models.capabilities import get_capabilities

    for pid, r in rendered.items():
        caps = get_capabilities(pid)
        expected = bool(caps and caps.has_interactive_signin)
        assert r["hasSigninButton"] is expected, (
            f"{pid}: sign-in button={r['hasSigninButton']} but "
            f"has_interactive_signin={expected}")


def test_ollama_offers_no_sign_in(rendered):
    """It has a local CLI but no account — a sign-in button would do nothing."""
    assert rendered["ollama"]["hasSigninButton"] is False
    assert rendered["ollama"]["hasApiKeyCard"] is False


def test_openrouter_is_key_only(rendered):
    """No OAuth flow is implemented, so don't advertise one."""
    assert rendered["openrouter"]["hasSigninButton"] is False
    assert rendered["openrouter"]["hasApiKeyCard"] is True


def test_a_disconnected_provider_shows_no_connected_badge(rendered):
    """Nothing is connected in a fresh catalog, so nothing may claim to be."""
    from lodestone.models.registry import get_model_catalog

    catalog = {p["id"]: p for p in get_model_catalog()}
    for pid, r in rendered.items():
        creds = catalog[pid].get("credentials") or {}
        if not (creds.get("api_key", {}).get("connected")
                or creds.get("account", {}).get("connected")):
            assert not r["connectedBadge"], f"{pid} rendered a Connected badge while disconnected"


# ── clicking "Sign in" must actually put something on screen ─────────────
CLICK_HARNESS = ROOT / "tests/js/click_signin.mjs"


@pytest.fixture(scope="module")
def catalog_json():
    from lodestone.models.registry import get_model_catalog

    return get_model_catalog()


def _click_signin(provider: str, catalog=None) -> dict:
    """Run the real click handler for a provider and report what the sign-in
    container ends up containing.

    The stub models DOM detachment: reassigning innerHTML clears the subtree, so
    a card written into a container that a preceding re-render replaced comes
    back empty — which is exactly the bug that made "Sign in with Cursor" do
    nothing. Asserting on source order does not catch that.
    """
    from lodestone.models.auth_flows import get_flow
    from lodestone.models.registry import get_model_catalog

    payload = json.dumps({
        "catalog": catalog if catalog is not None else get_model_catalog(),
        "authStartResponse": get_flow(provider).start().to_dict(),
    })
    proc = subprocess.run(["node", str(CLICK_HARNESS), str(APP_JS), provider],
                          input=payload, capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, f"click harness failed: {proc.stderr[:400]}"
    return json.loads(proc.stdout)


@pytest.mark.parametrize("provider", ["cursor", "claude-code", "xai"])
def test_cli_providers_show_instructions_when_sign_in_is_clicked(provider, catalog_json):
    """These have no browser flow — the button must explain what to run."""
    r = _click_signin(provider, catalog_json)
    assert r["clicked"], f"{provider} sign-in button has no handler"
    assert r["error"] is None, r["error"]
    assert r["containerHtml"], f"{provider}: clicking produced nothing on screen"
    assert "ts-cli-cmd" in r["containerHtml"], "no copyable command shown"
    assert "ts-cli-recheck" in r["containerHtml"], "no way to re-check after signing in"


def test_the_click_actually_asks_the_backend(catalog_json):
    r = _click_signin("cursor", catalog_json)
    assert any("/auth/start" in c for c in r["calls"]), "never called the auth endpoint"


def test_a_browser_provider_still_starts_a_browser_flow(catalog_json):
    """The CLI branch must not swallow providers that do have a real flow."""
    r = _click_signin("openai", catalog_json)
    assert r["error"] is None
    assert "ts-cli-cmd" not in r["containerHtml"], "OpenAI wrongly took the CLI branch"
