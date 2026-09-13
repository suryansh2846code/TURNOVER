"""The Models drawer must open quickly.

Building the catalog shells out to vendor CLIs and pokes local daemons, and
`/api/providers` and `/api/models/catalog` are both fetched every time the
drawer opens. Uncached that measured 5.7s + 4.4s on a real machine — the app
looked frozen and had to be force-quit.
"""
import time
from unittest.mock import patch

import pytest

from lodestone.config import forget_cached_secrets, get_settings
from lodestone.models import cache


@pytest.fixture(autouse=True)
def _cold():
    cache.clear_all()
    yield
    cache.clear_all()


def test_repeat_secret_reads_do_not_respawn_the_keychain():
    """~50 secrets are read per catalog build; each uncached read spawns
    `security`, which cost most of a second in process spawns alone."""
    settings = get_settings()
    forget_cached_secrets()
    # conftest forces the file path so tests never touch the real Keychain; turn
    # it back on here with a stubbed lookup, since that path is what we measure.
    with patch.object(type(settings), "_keychain_ok", return_value=True), \
         patch.object(type(settings), "_kc_get", return_value="sk-cached") as kc:
        assert settings.get_secret("SOME_PROVIDER_KEY") == "sk-cached"
        for _ in range(20):
            settings.get_secret("SOME_PROVIDER_KEY")
    assert kc.call_count == 1, f"keychain hit {kc.call_count} times for one secret"
    forget_cached_secrets()


def test_writing_a_secret_invalidates_the_cache():
    """A stale credential would be worse than a slow one."""
    settings = get_settings()
    forget_cached_secrets()
    with patch.object(type(settings), "_keychain_ok", return_value=True), \
         patch.object(type(settings), "_kc_get", return_value="old"):
        assert settings.get_secret("ROTATING_KEY") == "old"
    settings.set_secret("ROTATING_KEY", None)          # flushes
    with patch.object(type(settings), "_keychain_ok", return_value=True), \
         patch.object(type(settings), "_kc_get", return_value="new"):
        assert settings.get_secret("ROTATING_KEY") == "new"
    forget_cached_secrets()


def test_account_detection_is_not_repeated_within_one_drawer_open():
    """Both endpoints call it, and it shells out to `claude auth status`."""
    from lodestone.models import accounts

    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return {"provider": "claude", "connected": False, "found_on_computer": False}

    with patch.object(accounts, "detect_claude_account", counting), \
         patch.object(accounts, "detect_cursor_account", dict), \
         patch.object(accounts, "detect_openai_account", dict), \
         patch.object(accounts, "detect_xai_account", dict), \
         patch.object(accounts, "detect_google_account", dict):
        accounts.detect_all_accounts()
        accounts.detect_all_accounts()
        accounts.detect_all_accounts()
    assert calls["n"] == 1, "account detection repeated within the cache window"


def test_cli_model_listing_is_cached():
    """`agent --list-models` is a subprocess returning 223 rows; it measured
    3.1s and is hit on every catalog build."""
    from lodestone.models import cursor

    calls = {"n": 0}

    def counting(cmd, **kw):
        calls["n"] += 1
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, "auto - Auto\ncomposer-2.5 - Composer", "")

    cursor.cursor_cli_models.cache_clear()
    with patch("lodestone.models.cursor.find_cursor_cli", return_value="/x/agent"), \
         patch("subprocess.run", side_effect=counting):
        first = cursor.cursor_cli_models()
        for _ in range(5):
            cursor.cursor_cli_models()
    assert calls["n"] == 1, f"listed models {calls['n']} times"
    assert first and first[0][0] == "auto"
    cursor.cursor_cli_models.cache_clear()


def test_a_credential_change_flushes_every_probe_cache():
    """Connecting an account must be visible at once, not after a TTL."""
    from lodestone.models import accounts
    from lodestone.models.registry import clear_provider_cache

    with patch.object(accounts, "detect_claude_account", lambda: {"x": 1}), \
         patch.object(accounts, "detect_cursor_account", dict), \
         patch.object(accounts, "detect_openai_account", dict), \
         patch.object(accounts, "detect_xai_account", dict), \
         patch.object(accounts, "detect_google_account", dict):
        accounts.detect_all_accounts()
        clear_provider_cache("claude")
        calls = {"n": 0}

        def counting():
            calls["n"] += 1
            return {"x": 2}

        with patch.object(accounts, "detect_claude_account", counting):
            accounts.detect_all_accounts()
    assert calls["n"] == 1, "cache survived a credential change"


def test_a_warm_drawer_open_is_fast():
    """Guards the regression that made the app need force-quitting."""
    from fastapi.testclient import TestClient

    from lodestone.api.app import app

    client = TestClient(app)
    client.get("/api/providers")                 # warm
    client.get("/api/models/catalog")

    start = time.time()
    client.get("/api/providers")
    client.get("/api/models/catalog")
    elapsed = time.time() - start
    assert elapsed < 1.5, f"a warm drawer open took {elapsed:.2f}s"
