"""A secret that arrives through a connector must not be stored in the clear.

Brain v1.5 redacts credentials on the ingest path. That guarantee has been
tested at the brain's own door; it has never been tested from the direction the
secrets actually arrive from. People paste API keys into emails, Slack messages,
Notion pages and commit messages constantly, and a connector is the thing that
carries them in.

It matters twice over here. The brain is exported to `brain-export/` as
plaintext markdown, and it is read back to a model on every agent turn — so an
unmasked key is both written to a file the user may sync elsewhere and sent to
whichever provider they have selected.

This becomes load-bearing rather than precautionary the moment Phase 2 lets a
third-party MCP server write into the same path.
"""
from __future__ import annotations

import pytest

from . import harness
from .harness import FAKES

# One secret per recognised shape, so a connector cannot pass by masking only
# the pattern this test happened to pick.
SECRETS = {
    "openai": "sk-proj-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIIIJJJJKKKKLLLL",
    "xai": "xai-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIIIJJJJKKKK",
    "google": "AIzaSyAAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIII",
}

IDS = [f.name for f in FAKES]


@pytest.mark.parametrize("secret", SECRETS.values(), ids=list(SECRETS))
def test_a_secret_ingested_as_a_note_is_masked(secret):
    """The shortest path in: a connector writing free text straight to the brain."""
    from chitragupta.brain import get_brain
    from chitragupta.core.store import get_store

    get_brain().ingest(f"The staging key is {secret} — do not share it.",
                       source="notes", kind="note", fast=True)

    stored = " ".join(m.text for m in get_store().list(limit=20))
    assert secret not in stored, "a credential was stored verbatim"
    assert "REDACTED" in stored, "the secret vanished instead of being masked"


def test_redaction_survives_the_connector_path(monkeypatch, fake_module, tmp_path):
    """Same probe, but carried in by a real connector's real `sync()`.

    GitHub is the realistic case — a token pasted into an issue body — and it
    goes through `Brain.ingest`, which is the path every connector but Gmail and
    Apple Mail uses.
    """
    from chitragupta.connectors.github import GitHubConnector
    from chitragupta.core.store import get_store

    secret = SECRETS["openai"]
    items = [{"number": 1, "title": "CI is failing", "state": "open",
              "user": {"login": "someone"},
              "body": f"Export OPENAI_API_KEY={secret} before running the job.",
              "html_url": "https://github.com/acme/repo/issues/1",
              "repository": {"full_name": "acme/repo"}}]
    harness._set_secret("GITHUB_TOKEN", "ghp_testtoken")
    harness.install_urlopen(monkeypatch, items)

    GitHubConnector().sync(interactive=False)

    stored = " ".join(m.text for m in get_store().list(source="github", limit=20))
    assert stored, "the fixture never reached the store, so this proves nothing"
    assert secret not in stored, (
        "a credential pasted into an issue body was stored verbatim — it would "
        "be written to brain-export/ and sent to the model on every turn")


def test_the_rest_of_the_record_is_kept(monkeypatch, fake_module, tmp_path):
    """Redaction must mask the secret, not discard the memory around it.

    Dropping the whole record would be a quieter bug than storing it: the user
    loses content and is never told which, or why.
    """
    from chitragupta.brain import get_brain
    from chitragupta.core.store import get_store

    get_brain().ingest(
        f"Deploy notes for the launch: the key is {SECRETS['xai']}. "
        "Ask Dev before restarting the worker.",
        source="notes", kind="note", fast=True)

    stored = " ".join(m.text for m in get_store().list(limit=20))
    assert "Deploy notes for the launch" in stored
    assert "Ask Dev before restarting the worker" in stored
