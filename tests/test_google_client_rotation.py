"""The precedence chain that makes a Google client rotation possible.

`chitragupta/data/google_client.json` is committed on purpose (`DECISIONS.md` →
H12): a stranger installs the `.dmg`, presses *Sign in with Google*, and it
works. The cost of that decision is that one revocation — a secret scanner, or
abuse attributed to the Cloud project by someone who copied the public client id
— takes Gmail, Calendar and Drive down for *every* user at once.

Surviving that depends entirely on `Settings.google_client_secrets` preferring an
override to the bundled file, because that is what lets a replacement client be
proven against a real Google account *before* it is committed, and what lets one
affected user be unblocked by dropping a file instead of by shipping a release.

So this order is not a convenience. It is the recovery path, and
`docs/development/google-client-rotation.md` is fiction without it. Nothing
previously stopped a refactor from collapsing the three branches into "just read
the bundled one" — every test would have stayed green and the procedure would
have quietly stopped working, discovered on the worst possible day.

`Settings` is constructed directly rather than through `get_settings()`, which is
`lru_cache`d and would hand back whichever home the first caller happened to
build.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chitragupta.config import Settings

BUNDLED = Path(__file__).resolve().parents[1] / "chitragupta" / "data" / "google_client.json"


def _client_file(path: Path, client_id: str) -> Path:
    """A minimally realistic Desktop client, written where the test wants it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"installed": {
        "client_id": client_id,
        "project_id": "test-project",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_secret": "not-a-real-secret",
        "redirect_uris": ["http://localhost"],
    }}))
    return path


def test_bundled_client_ships_so_first_launch_works(tmp_path, monkeypatch):
    """Step 3 of the chain. Remove this and a fresh install cannot sign in."""
    monkeypatch.delenv("GOOGLE_CLIENT_SECRETS", raising=False)
    settings = Settings(home=tmp_path)

    assert settings.google_client_secrets == BUNDLED
    assert BUNDLED.exists(), "the bundled client is what makes first launch work"


def test_a_client_in_lodestone_home_beats_the_bundled_one(tmp_path, monkeypatch):
    """The unblock-one-user path: drop a file, no release, no terminal command
    beyond the copy itself."""
    monkeypatch.delenv("GOOGLE_CLIENT_SECRETS", raising=False)
    dropped = _client_file(tmp_path / "google_client_secret.json", "dropped-by-user")

    assert Settings(home=tmp_path).google_client_secrets == dropped


def test_the_env_override_beats_everything(tmp_path, monkeypatch):
    """The verify-before-committing path. A replacement client is exercised
    against a real Google account while the old one is still bundled *and* while
    a user-dropped file may also exist — so it has to win against both."""
    _client_file(tmp_path / "google_client_secret.json", "dropped-by-user")
    candidate = _client_file(tmp_path / "candidate.json", "the-replacement")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS", str(candidate))

    assert Settings(home=tmp_path).google_client_secrets == candidate


def test_an_override_pointing_nowhere_falls_through_rather_than_failing(tmp_path, monkeypatch):
    """A stale `GOOGLE_CLIENT_SECRETS` in someone's shell profile must not take
    Google sign-in down. It is a pointer, not an assertion that the file exists.
    """
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS", str(tmp_path / "deleted-last-week.json"))

    assert Settings(home=tmp_path).google_client_secrets == BUNDLED


def test_the_bundled_client_is_a_desktop_client(tmp_path, monkeypatch):
    """`InstalledAppFlow.from_client_secrets_file` requires the `installed` key.

    A *Web* client downloads as `{"web": {...}}` and is the single most likely
    way to get a rotation wrong — it looks identical in the Console listing and
    fails only at the consent step, on the user's machine.
    """
    monkeypatch.delenv("GOOGLE_CLIENT_SECRETS", raising=False)
    path = Settings(home=tmp_path).google_client_secrets
    assert path is not None
    client = json.loads(path.read_text())

    assert "installed" in client, "a Desktop client, not a Web client"
    assert client["installed"].get("client_id"), "needs a client_id to be usable"


@pytest.mark.parametrize("scope", [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
])
def test_the_scopes_the_rotation_check_expects_are_the_ones_we_request(scope):
    """The procedure's verification step asserts `granted_services()` returns
    Gmail, Drive and Calendar. That is only a meaningful check while these three
    read scopes are actually requested — otherwise it passes by omission.
    """
    from chitragupta.connectors.google_auth import SCOPES

    assert scope in SCOPES
