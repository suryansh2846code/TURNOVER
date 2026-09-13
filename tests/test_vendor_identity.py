"""Every identifier we send a vendor is either the vendor's or ours.

Lodestone reaches subscription plans through the vendors' own CLIs and public
PKCE clients — that is the sanctioned shape, and it is why a "Sign in with X"
button can work at all without a private client id. What it must never do is
present a *third* product's identity.

Two of these shipped: `originator=opencode` on the live ChatGPT sign-in, and
OpenCode's client id `b1a00492-…` with `referrer=opencode` in the xAI flow. Both
misreported who was calling, and both made every Lodestone user's sign-in
breakable by a vendor decision aimed at a project we have nothing to do with.

This test is a scan rather than an assertion about one file, because the next
one will be pasted into whichever module is being written at the time.
"""
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / "lodestone"

# Identifiers belonging to other people's products. A match in code is a bug;
# the modules below are allowed to *name* them in prose explaining the removal.
FOREIGN_IDENTIFIERS = ["opencode", "b1a00492-073a-47ea-816f-4c329264a828"]


def _code_lines(path: pathlib.Path):
    """Source lines with comments and docstring bodies stripped out.

    A crude filter on purpose: it must not be possible to satisfy this test by
    moving a borrowed id into a string that merely looks like documentation.
    """
    import io
    import tokenize

    try:
        with path.open("rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
    except (SyntaxError, tokenize.TokenError):  # pragma: no cover
        return []
    out = []
    for tok in tokens:
        if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE):
            continue
        if tok.type == tokenize.STRING and tok.line.strip().startswith(('"""', "'''")):
            continue                      # a docstring, not a value we send
        out.append((tok.start[0], tok.string))
    del io
    return out


@pytest.mark.parametrize("identifier", FOREIGN_IDENTIFIERS)
def test_no_other_products_identifier_is_ever_sent(identifier):
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        for lineno, text in _code_lines(path):
            if identifier in text.lower():
                offenders.append(f"{path.relative_to(SRC.parent)}:{lineno}")
    assert not offenders, (
        f"'{identifier}' belongs to another product and must not be sent to a "
        f"vendor. Found at: {', '.join(offenders)}")


def test_the_chatgpt_originator_matches_the_client_it_authenticates_as():
    """The originator names the app making the request. Sending one client id
    under a different product's name is the exact bug this replaced."""
    from lodestone.models import chatgpt_auth

    assert chatgpt_auth.ORIGINATOR == "codex_cli_rs"
    assert chatgpt_auth.CLIENT_ID.startswith("app_")


def test_xai_signin_holds_no_oauth_client_at_all():
    """The xAI OAuth flow was removed, not re-credentialed: an xAI OAuth token
    grants no api.x.ai credits, so the flow could never yield a usable
    credential. Sign-in goes through the vendor's Grok CLI, which owns its own
    client because it is the vendor's."""
    from lodestone.models import xai_auth

    for dead in ("CLIENT_ID", "REDIRECT_URI", "start_xai_oauth_flow"):
        assert not hasattr(xai_auth, dead), f"xai_auth.{dead} is back"


def test_an_expired_legacy_xai_token_is_dropped_not_refreshed(monkeypatch):
    """Refreshing needs the client id — which is precisely what we will not
    send. A user with a stale token is sent to the supported path instead."""
    import time

    from lodestone.models import xai_auth

    expired = {"tokens": {"access_token": "x", "refresh_token": "r"}}
    monkeypatch.setattr(xai_auth, "_load_stored_xai_data", lambda: expired)
    monkeypatch.setattr(xai_auth, "_decode_jwt_payload",
                        lambda _tok: {"exp": time.time() - 10})
    assert xai_auth.get_xai_access_token() is None


def test_a_live_legacy_xai_token_is_still_honoured(monkeypatch):
    """A user who signed in under the old build keeps working until it expires."""
    import time

    from lodestone.models import xai_auth

    live = {"tokens": {"access_token": "still-good"}}
    monkeypatch.setattr(xai_auth, "_load_stored_xai_data", lambda: live)
    monkeypatch.setattr(xai_auth, "_decode_jwt_payload",
                        lambda _tok: {"exp": time.time() + 3600})
    assert xai_auth.get_xai_access_token() == "still-good"
