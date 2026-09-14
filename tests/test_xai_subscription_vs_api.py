"""A Grok subscription is not an xAI API key.

`api.x.ai` is xAI's developer API, billed against credits bought at
console.x.ai. A SuperGrok subscription covers grok.com and the mobile apps and
grants no credits there — they are separate products with independent billing.
Signing in with Grok therefore authenticates fine and then fails *every*
request with 402 `personal-team-blocked:spending-limit`, including
`GET /v1/models`. We used to pass that OAuth token off as an API key, report
the provider ready, and surface the raw provider JSON to the user.
"""
from unittest.mock import patch

import httpx
import pytest
from web_sources import app_source

from lodestone.models.base import Message
from lodestone.models.xai import XAIProvider

BLOCKED = ('{"code":"personal-team-blocked:spending-limit","error":"You have run '
           'out of credits or need a Grok subscription. Add credits at https://grok.com"}')
HELLO = [Message(role="user", content="hi")]


def _oauth_only():
    with patch("lodestone.models.xai_auth.get_xai_access_token", return_value="oauth-token"), \
         patch("lodestone.models.base._saved_key", return_value=""), \
         patch.dict("os.environ", {}, clear=False):
        return XAIProvider(api_key=None)


def test_an_oauth_token_is_not_treated_as_an_api_key():
    p = _oauth_only()
    assert p._oauth_only is True
    assert p.api_key == "", "the OAuth token was passed off as an API credential"


def test_subscription_only_is_not_ready_and_says_why():
    ready, reason = _oauth_only().is_ready()
    assert ready is False
    assert "console.x.ai" in reason and "XAI_API_KEY" in reason


def test_a_real_api_key_is_ready():
    assert XAIProvider(api_key="xai-real-key").is_ready() == (True, "")


def test_spending_limit_is_explained_not_dumped():
    """The user used to see the provider's raw JSON."""
    resp = httpx.Response(402, request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
                          text=BLOCKED)
    with patch("httpx.post", return_value=resp):
        result = XAIProvider(api_key="xai-real-key").chat(HELLO)
    assert "personal-team-blocked" not in result.text, "raw provider JSON leaked to the user"
    assert "credits" in result.text and "console.x.ai" in result.text


def test_subscription_user_gets_the_subscription_explanation():
    resp = httpx.Response(402, request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
                          text=BLOCKED)
    p = _oauth_only()
    p.api_key = "oauth-token"          # force the request path
    with patch("httpx.post", return_value=resp):
        result = p.chat(HELLO)
    assert "SuperGrok subscription covers grok.com" in result.text


@pytest.mark.parametrize("status", [402, 403])
def test_billing_rejections_are_caught_on_any_status(status):
    resp = httpx.Response(status, request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
                          text=BLOCKED)
    with patch("httpx.post", return_value=resp):
        result = XAIProvider(api_key="xai-real-key").chat(HELLO)
    assert "credits" in result.text


def test_other_providers_get_a_generic_billing_message():
    from lodestone.models.deepseek import DeepSeekProvider

    resp = httpx.Response(402, request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
                          text='{"error":"insufficient balance"}')
    with patch("httpx.post", return_value=resp):
        result = DeepSeekProvider(api_key="sk-test").chat(HELLO)
    assert "billing" in result.text.lower() or "credits" in result.text.lower()


# ── xAI is offered as API-key-only ───────────────────────────────────────
def test_xai_offers_a_cli_sign_in_not_a_browser_one():
    """An OAuth/browser sign-in can never produce a usable api.x.ai credential.
    The subscription path is xAI's official Grok CLI instead."""
    from lodestone.models.capabilities import get_capabilities

    caps = get_capabilities("xai")
    assert caps.oauth_supported is False
    assert caps.browser_login_supported is False
    assert caps.local_cli_auth_supported is True
    assert caps.api_key_only is False


@pytest.mark.parametrize("pid,key_env", [
    ("gemini", "GEMINI_API_KEY"), ("deepseek", "DEEPSEEK_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
])
def test_signin_endpoint_explains_key_only_providers(pid, key_env):
    from fastapi.testclient import TestClient

    from lodestone.api.app import app

    body = TestClient(app).post(f"/api/providers/{pid}/signin").json()
    assert body["started"] is False
    assert body["api_key_only"] is True
    assert body["key_env"] == key_env
    assert "API key" in body["detail"]


@pytest.mark.parametrize("pid", ["openai", "claude", "cursor"])
def test_providers_with_a_real_sign_in_still_start_one(pid):
    from lodestone.models.capabilities import get_capabilities

    assert get_capabilities(pid).api_key_only is False


def test_frontend_derives_sign_in_cards_from_capabilities():
    """`app.js` must not reintroduce per-provider id checks."""

    src = app_source()
    assert 'providerId !== "gemini"' not in src
    assert 'caps.api_key_only' in src or "apiKeyOnly" in src


def test_grok_subscription_deferral_is_documented():
    """The deferral must record the real path (xAI's official Grok Build CLI),
    not the earlier wrong claim that it needed a private endpoint."""
    from pathlib import Path

    roadmap = (Path(__file__).parent.parent / "docs/ROADMAP.md").read_text()
    assert "Grok subscription support" in roadmap
    assert "personal-team-blocked:spending-limit" in roadmap
    assert "grok -p" in roadmap, "the sanctioned CLI path is not recorded"
