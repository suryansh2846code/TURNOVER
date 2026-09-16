"""A shipped app must not be configured by a file it found in someone's home.

`config.py` called `load_dotenv()` with no path, and `packaging/launcher.py`
chdirs to `Path.home()` before starting — a bundle's cwd is `/`, so that chdir
is itself correct. Together they meant the shipped `.app` read **`~/.env`**.

Plenty of developers have one there for something else entirely. Theirs would
silently set `CHITRAGUPTA_MODEL_PROVIDER`, `CHITRAGUPTA_PORT` or the embedding
backend for an app that has nothing to do with it, and the only symptom is an
app that behaves oddly for reasons nothing in the UI can explain.
"""
from __future__ import annotations

from chitragupta import config


def test_a_frozen_app_ignores_dotenv(monkeypatch):
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    assert not config.uses_dotenv(), (
        "the bundled app would read ~/.env and take its configuration from "
        "whatever happened to be in the user's home directory")


def test_a_source_checkout_still_reads_dotenv(monkeypatch):
    """The developer path is unchanged — .env is how this repo is configured."""
    monkeypatch.delattr(config.sys, "frozen", raising=False)
    assert config.uses_dotenv()


def test_the_settings_env_file_follows_the_same_decision():
    """`env_file` is bound at import, so it cannot be monkeypatched here — but
    it must be wired to the same function rather than hardcoded, or the guard
    above only covers half the path (pydantic-settings reads the file itself,
    independently of `load_dotenv`)."""
    env_file = config.Settings.model_config.get("env_file")
    assert env_file == (".env" if config.uses_dotenv() else None)
    # Under test we are never frozen, so this also pins that the developer
    # experience did not regress.
    assert env_file == ".env"
