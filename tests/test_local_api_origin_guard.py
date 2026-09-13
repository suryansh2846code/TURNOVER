"""The local API must not be reachable by a website the user happens to visit.

Lodestone serves on `127.0.0.1` with no authentication, which is normal for a
local app and is exactly why these tests exist: the same server lists the user's
home directory, stores provider credentials and can erase the brain, and every
browser on the machine is also "on the machine".

Each test below stands for one attack that works against an unguarded localhost
server, from a page the user merely opened in another tab.
"""
import pytest
from fastapi.testclient import TestClient

from lodestone.api.app import app
from lodestone.api.security import (
    is_local_origin,
    is_loopback_host,
    is_safe_external_url,
    refusal,
    same_origin,
)

client = TestClient(app)

# Endpoints worth naming individually, because each is a different flavour of
# damage: reading the user's disk, writing a credential, destroying the brain.
SENSITIVE_READS = ["/api/fs/browse", "/api/providers", "/api/providers/connections"]
SENSITIVE_WRITES = ["/api/brain/reset", "/api/providers/claude/key", "/api/open-browser"]


def test_a_rebinding_page_cannot_read_the_api():
    """DNS rebinding: evil.com resolves to 127.0.0.1, so the browser treats the
    page as same-origin and will hand it the response body. The `Host` header
    is the one thing the attacker cannot forge — it still says evil.com."""
    for path in SENSITIVE_READS:
        r = client.get(path, headers={"host": "evil.com"})
        assert r.status_code == 403, f"{path} answered a rebinding request"
        assert "another machine" in r.json()["detail"]


def test_a_rebinding_page_cannot_reach_the_home_directory():
    """The concrete worst case: /api/fs/browse enumerates the user's disk."""
    r = client.get("/api/fs/browse", params={"path": "/"}, headers={"host": "attacker.test"})
    assert r.status_code == 403
    assert "dirs" not in r.text


def test_a_foreign_page_cannot_post():
    """CSRF: a cross-site POST succeeds even when the reply is unreadable, so
    `/api/brain/reset` would erase the brain of anyone who visited the page."""
    for path in SENSITIVE_WRITES:
        r = client.post(path, json={}, headers={"origin": "https://evil.com"})
        assert r.status_code == 403, f"{path} accepted a cross-origin POST"


def test_the_browsers_own_verdict_is_honoured():
    """Modern browsers state who started the request; we do not have to infer it."""
    r = client.get("/api/providers", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403


def test_an_opaque_origin_is_foreign_not_missing():
    """A sandboxed iframe or a file:// page sends `Origin: null`. Treating that
    as "no origin" would let precisely the least trustworthy caller through."""
    r = client.post("/api/brain/reset", json={}, headers={"origin": "null"})
    assert r.status_code == 403


def test_our_own_page_still_works():
    """The guard is worthless if it also blocks the app. Our page's Origin is
    always the authority the request arrived on."""
    ok = {"host": "127.0.0.1:8787", "origin": "http://127.0.0.1:8787",
          "sec-fetch-site": "same-origin"}
    assert client.get("/api/providers", headers=ok).status_code == 200
    assert client.get("/api/fs/browse", headers=ok).status_code == 200


# Ports that a developer very plausibly has open in another tab while using
# Lodestone. Every one of them is loopback, and none of them is us.
OTHER_LOCAL_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:5173",
                       "http://localhost:8888", "http://127.0.0.1:8080"]


@pytest.mark.parametrize("origin", OTHER_LOCAL_ORIGINS)
def test_another_app_on_another_local_port_is_still_a_website(origin):
    """The gap an audit found in the first version of this guard.

    "Is the Origin loopback?" is not the same question as "is the Origin us?".
    A Vite dev server, a notebook, or any other local web app the user has open
    passes the first and fails the second — and could otherwise have POSTed to
    `/api/brain/reset` or read the home directory through `/api/fs/browse`.
    """
    headers = {"host": "127.0.0.1:8787", "origin": origin,
               "sec-fetch-site": "same-site"}
    assert not same_origin(origin, "127.0.0.1:8787")
    for path in SENSITIVE_WRITES:
        assert client.post(path, json={}, headers=headers).status_code == 403, path
    assert client.get("/api/fs/browse", headers=headers).status_code == 403


def test_the_port_is_what_makes_an_origin_ours():
    """The desktop app serves on a different random port every install, so this
    cannot be a fixed list — it is a comparison against the request's own Host."""
    assert same_origin("http://127.0.0.1:63920", "127.0.0.1:63920")
    assert not same_origin("http://127.0.0.1:63921", "127.0.0.1:63920")
    assert not same_origin("http://127.0.0.1", "127.0.0.1:8787")


def test_both_spellings_of_this_machine_are_the_same_origin():
    """A user may reach the browser build as `localhost` or as `127.0.0.1`;
    whichever they use, the page and its requests agree. Treating the two names
    as one keeps that from being a special case — the port still has to match,
    and an attacker cannot serve from our port anyway."""
    assert same_origin("http://localhost:8787", "127.0.0.1:8787")
    assert same_origin("http://127.0.0.1:8787", "localhost:8787")
    assert not same_origin("http://localhost:8788", "127.0.0.1:8787")


def test_a_request_with_no_origin_is_left_to_the_host_check():
    """Top-level navigations and non-browser callers send no Origin. Refusing
    them would break opening the app; the Host check is what covers that case."""
    assert refusal("POST", {"host": "127.0.0.1:8787"}) is None
    assert refusal("POST", {"host": "evil.com"}) is not None


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8787", "localhost:8787", "[::1]:8787"])
def test_every_name_for_this_machine_is_accepted(host):
    """The desktop app serves on a random port and the browser build on 8787;
    users reach both by more than one name."""
    assert is_loopback_host(host)
    assert client.get("/api/providers", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.com", "127.0.0.1.evil.com", "notlocalhost", ""])
def test_lookalike_hosts_are_refused(host):
    """A suffix match would accept `127.0.0.1.evil.com`, which is a name the
    attacker owns and can point wherever they like."""
    assert not is_loopback_host(host)


@pytest.mark.parametrize("origin", ["https://evil.com", "http://localhost.evil.com", "null", ""])
def test_foreign_origins_are_refused(origin):
    assert not is_local_origin(origin)


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8787", "http://localhost:5000",
                                    "https://127.0.0.1", "http://[::1]:9000"])
def test_local_origins_are_accepted(origin):
    assert is_local_origin(origin)


def test_the_policy_is_a_function_not_only_a_server():
    """Kept testable on its own so the rules can be read and checked directly."""
    assert refusal("GET", {"host": "127.0.0.1:8787"}) is None
    assert refusal("GET", {"host": "evil.com"}) is not None
    assert refusal("POST", {"host": "127.0.0.1", "origin": "https://evil.com"}) is not None
    assert refusal("POST", {"host": "127.0.0.1:8787",
                            "origin": "http://127.0.0.1:8787"}) is None
    # Loopback, but not us.
    assert refusal("POST", {"host": "127.0.0.1:8787",
                            "origin": "http://localhost:3000"}) is not None
    # A non-browser caller (curl, a script, this test) sends neither header.
    assert refusal("POST", {"host": "127.0.0.1"}) is None


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "",
                                 "someapp://run", "https://x.ai\nHeader: x"])
def test_open_browser_refuses_anything_that_is_not_a_web_page(url):
    """`/api/open-browser` exists to show a vendor's sign-in page. Without a
    scheme check it hands the system opener any scheme an installed app has
    registered — or a local file."""
    assert not is_safe_external_url(url)
    r = client.post("/api/open-browser", json={"url": url})
    assert r.status_code == 400


def test_open_browser_still_opens_a_sign_in_page(monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u) or True)
    assert client.post("/api/open-browser", json={"url": "https://claude.com/login"}).status_code == 200
    assert opened == ["https://claude.com/login"]


def test_responses_are_not_embeddable_or_sniffable():
    """Nothing here is meant to be framed by, or loaded into, another page."""
    h = client.get("/api/providers").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Cross-Origin-Resource-Policy"] == "same-origin"


def test_the_ui_is_guarded_too():
    """Rebinding that can load the page can read whatever the page renders."""
    assert client.get("/", headers={"host": "evil.com"}).status_code == 403
    assert client.get("/static/app.js", headers={"host": "evil.com"}).status_code == 403
