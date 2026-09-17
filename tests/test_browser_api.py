"""The allow-list, reachable from the product.

`browser/origins.py` decides who may read what; this is the only way a *person*
changes that decision. Two properties matter more than the CRUD:

**An agent cannot reach these routes.** Nothing in `agents/` calls them and
`browse_tools` has no path into `origins.grant`. If that ever stops being true,
an agent talked into wanting more access can take it, and the list stops meaning
anything.

**A bad address is refused with a sentence.** The field is typed by a person, so
`http://`, a bare `localhost` and a numeric address all come back with something
that says what to change — not a validation code and not a 500.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from chitragupta.api.app import app
from chitragupta.browser import origins


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def no_sites():
    conn = origins._conn()
    conn.execute("DELETE FROM browser_origins")
    conn.commit()
    yield


# ── the list ────────────────────────────────────────────────────────────
def test_a_fresh_install_allows_nothing(client):
    body = client.get("/api/browser/status").json()

    assert body["sites"] == []
    assert body["installed"] is False


def test_allowing_a_site_by_bare_host_works(client):
    """The field is typed by a person. Making somebody write `https://` is
    making them do the parser's job."""
    body = client.post("/api/browser/sites", json={"url": "linkedin.com"}).json()

    assert body["origin"] == "https://linkedin.com"
    assert body["may_read"] is True
    assert body["may_act"] is False, "reading only, and never by accident"


def test_an_allowed_site_shows_up_in_both_places(client):
    client.post("/api/browser/sites", json={"url": "payroll.example.com"})

    assert [s["host"] for s in client.get("/api/browser/sites").json()["sites"]] \
        == ["payroll.example.com"]
    assert [s["host"] for s in client.get("/api/browser/status").json()["sites"]] \
        == ["payroll.example.com"]


def test_removing_a_site_takes_effect_for_the_tools_immediately(client):
    """Anything the user can grant they can take back, and it has to bite now
    rather than at the next launch."""
    client.post("/api/browser/sites", json={"url": "linkedin.com"})
    assert origins.may_read("https://linkedin.com/feed").allowed

    assert client.delete("/api/browser/sites/linkedin.com").json()["revoked"] is True

    assert origins.may_read("https://linkedin.com/feed").allowed is False


def test_removing_something_that_was_never_there_is_not_an_error(client):
    assert client.delete("/api/browser/sites/nope.example.com").json()["revoked"] is False


# ── refusals a person can act on ────────────────────────────────────────
@pytest.mark.parametrize("bad, expect", [
    ("http://linkedin.com", "https"),
    ("localhost", "website"),
    ("https://127.0.0.1", "numeric"),
    ("javascript:alert(1)", "website"),
    ("", "no address"),
])
def test_a_bad_address_is_refused_with_a_sentence(client, bad, expect):
    response = client.post("/api/browser/sites", json={"url": bad})

    assert response.status_code == 400
    assert expect in response.json()["detail"].lower()


def test_a_refused_address_is_not_stored(client):
    client.post("/api/browser/sites", json={"url": "http://linkedin.com"})

    assert origins.list_grants() == []


# ── setup ───────────────────────────────────────────────────────────────
def test_status_says_whether_a_page_can_actually_be_opened(client):
    """`drivable` is what stops the UI offering a Set up button in a build that
    cannot drive a browser — a control that cannot work reads as breakage.

    Asserted against `can_drive()` rather than against `False`. The first version
    of this test hardcoded the answer, which was true only because Playwright
    happened not to be installed that afternoon; it started failing the moment
    the driver landed, having tested the machine rather than the contract.
    """
    from chitragupta.browser import chromium

    body = client.get("/api/browser/status").json()

    assert body["drivable"] is chromium.can_drive()
    assert isinstance(body["drivable"], bool), "the UI switches on this"
    assert body["approx_mb"], "the download size is said before it starts"


def test_install_reports_rather_than_raises(client):
    """It is a button. A 500 here is a dead end with no explanation."""
    body = client.post("/api/browser/install").json()

    assert "state" in body
    assert body["state"] in {"idle", "running", "done", "error"}


def test_forgetting_everything_answers_even_with_no_profile(client):
    assert "forgotten" in client.post("/api/browser/forget-everything").json()


# ── the boundary between a person and an agent ──────────────────────────
def test_no_agent_tool_can_reach_these_routes():
    """The property that makes the list real.

    Checked in the source rather than by behaviour, because the failure is
    somebody *adding* a call — and a behavioural test cannot fail for code that
    does not exist yet.
    """
    from pathlib import Path

    from chitragupta.agents import browse_tools

    text = Path(browse_tools.__file__).read_text(encoding="utf-8")

    assert "api/browser" not in text
    assert "origins.grant" not in text
    assert "origins.revoke" not in text
