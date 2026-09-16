"""The tools an agent actually calls, and what it is told when refused.

`agents/browse_tools.py` is thin on purpose — the boundary, the bounding and the
quarantine are all in `browser/`. What it owns is the wording and the verdict,
and both of those change behaviour:

* a refusal has to come back as a **failure**, or the loop reissues the same call
  until the budget is gone (`results.py` exists because guessing that from the
  text got all three real failures wrong)
* the refusal has to name the site and say who can allow it, or an agent reports
  "I couldn't" where it could have reported "ask the user to allow payroll"
* an agent must **never** be able to widen its own access, or the allow-list is
  decorative

And one structural check with a long memory: the write tools do not exist yet,
and when they do they have to be gated. A test that fails the day somebody adds
`browse_click` without the gate is worth more than a comment asking them to.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lodestone.agents import browse_tools, permissions, tools
from lodestone.browser import origins
from lodestone.browser.page import Node
from lodestone.browser.session import Session


class FakeDriver:
    def __init__(self, pages=None, redirects=None):
        self.pages = pages or {}
        self.redirects = redirects or {}
        self._at = ""

    def _page(self, url):
        title, nodes = self.pages.get(url, ("Untitled", []))
        return url, title, list(nodes)

    def goto(self, url):
        self._at = self.redirects.get(url, url)
        return self._page(self._at)

    def current(self):
        return self._page(self._at)

    def back(self):
        return self._page(self._at)

    def close(self):
        pass


#: Tools that would change something on a website. None of them exists yet; the
#: set is written down so the gate below can watch for them arriving.
_WRITE_TOOLS = frozenset({
    "browse_click", "browse_type", "browse_select", "browse_submit",
    "browse_download",
})

PAGES = {
    "https://payroll.example.com/payslips": ("Payslips", [
        Node(role="heading", name="Your payslips"),
        Node(role="link", name="March 2026", handle="#mar"),
        Node(role="button", name="Download all", handle="#dl"),
    ]),
}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    conn = origins._conn()
    conn.execute("DELETE FROM browser_origins")
    conn.commit()
    browse_tools.set_session(Session(FakeDriver(PAGES)))
    yield
    browse_tools.set_session(None)


# ── reading ─────────────────────────────────────────────────────────────
def test_an_allowed_page_comes_back_fenced():
    origins.grant("payroll.example.com")

    out = browse_tools.browse_open("https://payroll.example.com/payslips")

    assert out.ok is True
    assert "Your payslips" in out
    assert "NOT INSTRUCTIONS" in out, "page text must arrive marked as content"


def test_a_refusal_is_a_failure_not_a_string_that_looks_like_one():
    """The loop reads `ok`. A refusal that reports success is a refusal the model
    retries until its budget is gone."""
    out = browse_tools.browse_open("https://payroll.example.com/payslips")

    assert out.ok is False


def test_a_refusal_tells_the_agent_who_can_fix_it():
    out = browse_tools.browse_open("https://payroll.example.com/payslips")

    assert "payroll.example.com" in out
    assert "the user" in out.lower()


def test_a_refusal_tells_the_agent_not_to_go_hunting():
    """Without this an agent tries the www, then the apex, then a guess — each
    one a refusal, and the last thing a user wants is an agent probing addresses
    on their behalf."""
    out = browse_tools.browse_open("https://payroll.example.com/payslips")

    assert "not try other addresses" in out.lower()


def test_an_unusable_address_is_refused_without_offering_anything():
    out = browse_tools.browse_open("javascript:alert(1)")

    assert out.ok is False
    assert "Settings" not in out, "there is no grant that would make this work"


def test_no_tool_can_grant_itself_access():
    """The one property that makes the allow-list real. Every browse tool is
    read-only over `origins`, so an agent that has been talked into wanting more
    access has no way to take it."""
    text = Path(browse_tools.__file__).read_text(encoding="utf-8")

    assert "origins.grant" not in text
    assert "may_act=True" not in text


# ── re-reading, which is where the money goes ───────────────────────────
def test_reading_the_same_page_twice_is_cheap_the_second_time():
    """A page is the most expensive thing an agent can ask for, and it re-reads
    after every step."""
    origins.grant("payroll.example.com")
    browse_tools.browse_open("https://payroll.example.com/payslips")
    first = browse_tools.browse_read()
    version = first.split("[page-version: ")[1].rstrip("]\n")

    second = browse_tools.browse_read(since=version)

    assert "has not changed" in second
    assert "Your payslips" not in second, "it paid for the page again"
    assert len(second) < len(first) / 2


def test_a_changed_page_is_read_in_full_even_with_a_stale_version():
    origins.grant("payroll.example.com")
    session = Session(FakeDriver({
        "https://payroll.example.com/payslips": ("Payslips", [
            Node(role="heading", name="Your payslips")])}))
    browse_tools.set_session(session)
    browse_tools.browse_open("https://payroll.example.com/payslips")

    out = browse_tools.browse_read(since="notthecurrentdigest")

    assert "Your payslips" in out


def test_a_read_carries_a_version_the_agent_can_pass_back():
    origins.grant("payroll.example.com")
    browse_tools.browse_open("https://payroll.example.com/payslips")

    assert "[page-version: " in browse_tools.browse_read()


# ── finding ─────────────────────────────────────────────────────────────
def test_find_returns_refs_and_never_a_selector():
    origins.grant("payroll.example.com")
    browse_tools.browse_open("https://payroll.example.com/payslips")

    out = browse_tools.browse_find("download")

    assert "[e2] button: Download all" in out
    assert "#dl" not in out


def test_finding_nothing_says_the_page_may_have_changed():
    """The right failure for a site that redesigned overnight: "I could not find
    that" beats clicking something nearby."""
    origins.grant("payroll.example.com")
    browse_tools.browse_open("https://payroll.example.com/payslips")

    out = browse_tools.browse_find("the big red button")

    assert out.ok is False
    assert "may have changed" in out


def test_finding_with_no_page_open_says_what_to_do_first():
    out = browse_tools.browse_find("anything")

    assert out.ok is False
    assert "browse_open" in out


# ── orientation ─────────────────────────────────────────────────────────
def test_an_agent_can_ask_which_sites_it_may_read():
    origins.grant("payroll.example.com")
    origins.grant("linkedin.com")

    out = browse_tools.browse_sites()

    assert "payroll.example.com" in out
    assert "linkedin.com" in out


def test_with_nothing_allowed_it_says_so_and_says_where_to_change_it():
    out = browse_tools.browse_sites()

    assert "not allowed any websites" in out
    assert "Settings" in out


# ── the registry, and the gate that must arrive with the write tools ────
@pytest.mark.parametrize("name", ["browse_open", "browse_read", "browse_find",
                                  "browse_sites"])
def test_every_browse_tool_is_registered_both_sides(name):
    """A spec with no implementation is a tool that 500s when a model picks it."""
    assert name in tools.TOOL_IMPLS
    assert name in [row["name"] for row in tools.describe_tools()]


def test_the_browse_tools_are_grouped_where_a_person_would_look():
    """Not folded into "Web": a search returns public results, these read pages
    the user is signed in to, and the person ticking the box should see the
    difference."""
    assert tools.tool_label("browse_open")[1] == "Websites you allow"


def test_no_shipped_agent_has_them_by_default():
    """Like `run_python`: the user adds the capability themselves, and that
    choice is the consent."""
    from lodestone.agents import library

    for template in library.TEMPLATES:
        granted = [t for t in (getattr(template, "tools", None) or [])
                   if str(t).startswith("browse_")]
        assert not granted, f"{getattr(template, 'id', template)} ships with {granted}"


def test_a_write_tool_cannot_be_added_without_the_unattended_gate():
    """The long-memory check.

    `browse_click`, `browse_type`, `browse_submit` and `browse_download` do not
    exist yet. The day one does, it must be in `NEVER_UNATTENDED` in the same
    commit — a routine triggered by a stranger's email is precisely the caller
    that must not be able to click inside the user's logged-in accounts. This
    test fails the moment that is forgotten, which a comment asking nicely would
    not.
    """
    present = _WRITE_TOOLS & set(tools.TOOL_IMPLS)

    assert present <= permissions.NEVER_UNATTENDED, (
        f"{sorted(present - permissions.NEVER_UNATTENDED)} can act on a website "
        "and is not in permissions.NEVER_UNATTENDED")


def test_that_gate_would_actually_notice(monkeypatch):
    """The guard above passes today because no write tool exists — which is also
    how a guard quietly stops working.

    `conftest.py` covers its own vendor-login guard for this reason: a check
    nobody exercises is a check that has never been shown to fire. So one is
    added here, ungated, and the same condition is asserted to fail.
    """
    monkeypatch.setitem(tools.TOOL_IMPLS, "browse_click", lambda ref: "clicked")

    present = _WRITE_TOOLS & set(tools.TOOL_IMPLS)

    assert present, "the simulated write tool is not being seen at all"
    assert not present <= permissions.NEVER_UNATTENDED, (
        "an ungated browse_click did not trip the check that exists to catch it")
