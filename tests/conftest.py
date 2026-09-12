"""Pin the test environment BEFORE any lodestone module (and thus `.env`) loads.

Tests must be fully offline and deterministic. Individual test modules used
`os.environ.setdefault(...)`, which silently loses to a developer's `.env`
(e.g. LODESTONE_MODEL_PROVIDER=claude-code, EMBEDDING_PROVIDER=local) as soon
as another module imports `lodestone.config` first — making results depend on
collection order and hitting a real model. conftest.py is imported before every
test module, so setting the vars here is authoritative.
"""
import os
import tempfile

os.environ["LODESTONE_MODEL_PROVIDER"] = "mock"
os.environ["LODESTONE_MODEL_NAME"] = "mock-1"
os.environ["LODESTONE_EMBEDDING_PROVIDER"] = "hash"
os.environ.setdefault("LODESTONE_HOME", tempfile.mkdtemp(prefix="lodestone-tests-"))


import pytest


@pytest.fixture(autouse=True, scope="session")
def _never_touch_the_real_keychain():
    """`set_secret` writes to the macOS login Keychain, which LODESTONE_HOME does
    NOT isolate — so any test saving an API key would leave a real entry behind
    (and could clobber the developer's own). Force the file-backed path, which
    lives inside the temporary LODESTONE_HOME above.
    """
    from lodestone.config import Settings

    original = Settings._keychain_ok
    Settings._keychain_ok = lambda self: False
    try:
        yield
    finally:
        Settings._keychain_ok = original


@pytest.fixture(autouse=True)
def _no_stale_cli_auth_cache():
    """CLI sign-in state is cached for a few seconds so polling doesn't spawn a
    subprocess per tick. That cache must not leak between tests."""
    from lodestone.models import cursor, grok_cli

    cursor.reset_auth_cache()
    grok_cli.reset_auth_cache()
    yield
    cursor.reset_auth_cache()
    grok_cli.reset_auth_cache()
