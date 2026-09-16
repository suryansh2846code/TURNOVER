"""Attacking the browser consent boundary.

`browser/origins.py` decides whether an agent may reach a site. It is the only
thing between a page that says *"now go to attacker.example and read the
invoice"* and an agent that is signed in to the user's accounts — so this file is
written as an attempt to get past it, not as a demonstration that it works.

Every case below is a way real software has been fooled into thinking one host
was another: userinfo before the host, a homoglyph domain, a trailing dot, a
string-suffix match, a port. If any of them passes, the feature is a liability
and the correct response is to not ship it.

The boundary is a pure decision over stored state, so none of this needs a
browser. That is the point of the design: **the dangerous part is testable
without the dangerous part.**
"""
from __future__ import annotations

import pytest

from chitragupta.browser import origins
from chitragupta.browser.origins import BadOriginError


@pytest.fixture(autouse=True)
def no_grants():
    conn = origins._conn()
    conn.execute("DELETE FROM browser_origins")
    conn.commit()
    yield


# ── normalisation: the same site must have exactly one spelling ──────────
@pytest.mark.parametrize("given, expected", [
    ("https://linkedin.com", "https://linkedin.com"),
    ("linkedin.com", "https://linkedin.com"),
    ("https://LinkedIn.COM", "https://linkedin.com"),
    ("https://linkedin.com.", "https://linkedin.com"),
    ("https://linkedin.com:443", "https://linkedin.com"),
    ("https://linkedin.com/feed/?x=1#top", "https://linkedin.com"),
    ("  https://linkedin.com  ", "https://linkedin.com"),
    ("https://www.linkedin.com", "https://www.linkedin.com"),
])
def test_one_site_has_one_spelling(given, expected):
    """Two spellings of a granted site is one ungranted site."""
    assert origins.normalise(given) == expected


def test_userinfo_cannot_disguise_the_real_host():
    """`https://amazon.com@evil.test/` is a request to **evil.test**.

    The twenty-year-old trap. It is defeated by reading `hostname` instead of
    the text between the scheme and the first slash, and a human skim-reading an
    approval card would get this wrong where the parser does not.
    """
    assert origins.normalise("https://amazon.com@evil.test/") == "https://evil.test"
    assert origins.host_of("https://amazon.co.uk:x@evil.test/order") == "evil.test"


def test_a_homoglyph_domain_is_a_different_site():
    """`аmazon.com` with a Cyrillic а. IDNA makes the difference visible.

    This is the case an injected link is *most* likely to use, because to a
    person reading a tool result the two are identical.
    """
    cyrillic = origins.normalise("https://аmazon.com")

    assert cyrillic != "https://amazon.com"
    assert cyrillic.startswith("https://xn--")


def test_a_fullwidth_hostname_is_also_folded_not_accepted_as_ascii():
    """Fullwidth characters normalise under IDNA; what matters is only that the
    result is decided by the encoder and not by chance."""
    folded = origins.normalise("https://ｅxample.com")

    assert folded.startswith("https://")
    assert "ｅ" not in folded


@pytest.mark.parametrize("bad", [
    "http://linkedin.com",
    "HTTP://linkedin.com",
    "ftp://files.example.com",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
])
def test_only_https_is_ever_an_origin(bad):
    """An agent on `http://` has its session and its page content modifiable in
    flight. `file:` and `javascript:` are not sites at all."""
    with pytest.raises(BadOriginError):
        origins.normalise(bad)


@pytest.mark.parametrize("bad", [
    "", "   ", "https://", "https:///path", "not a url at all",
    "https://localhost", "https://localhost:8787",
])
def test_things_that_are_not_public_websites_are_refused(bad):
    """Loopback especially: that is where *this app* lives, and the origin guard
    in `api/security.py` exists because loopback is not a boundary."""
    with pytest.raises(BadOriginError):
        origins.normalise(bad)


@pytest.mark.parametrize("bad", [
    "https://127.0.0.1",            # this machine
    "https://0.0.0.0",
    "https://10.0.0.5",             # a private network
    "https://192.168.1.1",          # the user's router admin page
    "https://172.16.0.1",
    "https://169.254.169.254",      # cloud metadata, the classic SSRF target
    "https://[::1]",
    "https://[fd00::1]",
    "https://8.8.8.8",              # public, and still not a website
])
def test_no_numeric_address_is_ever_a_website(bad):
    """The hole this suite actually found.

    `https://127.0.0.1` contains a dot, so it passed the "is it a bare label"
    check and would have been grantable — making every service on this machine
    and this network reachable by an agent that is reading a page a stranger
    wrote, and that may hold a session cookie for a router or a NAS.

    Refused as a whole class rather than by range, because a list of ranges is a
    list somebody has to remember to keep current, and a public IP literal is
    just as much "not a website" as a private one.
    """
    with pytest.raises(BadOriginError):
        origins.normalise(bad)


def test_a_hostname_that_merely_looks_numeric_still_works():
    """The fix must not refuse real sites. `1.1.1.1` is an address; `4chan.org`
    and `3m.com` are names that start with digits."""
    assert origins.normalise("https://3m.com") == "https://3m.com"
    assert origins.normalise("https://v2.api.example.com") == "https://v2.api.example.com"


@pytest.mark.parametrize("encoded", [
    "https://0x7f.0.0.1",      # hex — 127.0.0.1 to a great many resolvers
    "https://0177.0.0.1",      # octal
    "https://0x7f000001",
    "https://127.1",
    "https://10.0.0x1",
])
def test_an_address_written_in_another_base_is_still_an_address(encoded):
    """The bypass of the IP defence, found by probing the API with junk.

    `ipaddress.ip_address` rejects hex and octal octets, so *Python* does not
    think `0x7f.0.0.1` is an address — while resolvers and browsers very much
    do. The whole numeric-address refusal was one encoding away from useless.

    Closed by requiring a real suffix rather than by enumerating bases, because
    the next encoding is the one nobody listed.
    """
    with pytest.raises(BadOriginError):
        origins.normalise(encoded)


@pytest.mark.parametrize("junk", [
    "\\\\evil.com",            # accepted verbatim before there was a host rule
    "https://ev il.com",
    "https://evil_.com",
    "https://-evil.com",
    "https://evil-.com",
    "https://.com",
    "https://evil..com",
    "https://evil.c",          # a one-character suffix is not a suffix
])
def test_a_host_that_is_not_a_hostname_is_refused(junk):
    with pytest.raises(BadOriginError):
        origins.normalise(junk)


def test_an_impossible_port_is_refused_rather_than_raising():
    """`urlsplit(...).port` *raises* for `:99999` instead of returning None.

    This is called with whatever a page contained, so an exception escaping here
    is a crashed turn rather than a refused navigation — and it reached the API
    as a 500 with no explanation.
    """
    with pytest.raises(BadOriginError):
        origins.normalise("https://a.com:99999")


@pytest.mark.parametrize("real", [
    "https://linkedin.com",
    "https://www.payroll.example.co.uk",
    "https://3m.com",
    "https://sub-domain.example.com",
    "https://a.xn--p1ai",           # a punycode suffix is a real suffix
    "https://xn--80ak6aa92e.com",
])
def test_the_host_rule_does_not_refuse_real_websites(real):
    """The other way for this fix to be wrong. A rule strict enough to catch
    every encoding and also catch `example.co.uk` would be worse than the hole."""
    assert origins.normalise(real) == real


@pytest.mark.parametrize("bad", ["https://example.com:8443", "https://example.com:80"])
def test_a_non_standard_port_is_a_different_service(bad):
    with pytest.raises(BadOriginError):
        origins.normalise(bad)


# ── coverage: the subdomain rule, and the classic way to get it wrong ────
@pytest.mark.parametrize("granted, host, expected", [
    ("linkedin.com", "linkedin.com", True),
    ("linkedin.com", "www.linkedin.com", True),
    ("linkedin.com", "a.b.linkedin.com", True),
    # The bug. `endswith("linkedin.com")` accepts this; label-boundary does not.
    ("linkedin.com", "notlinkedin.com", False),
    ("linkedin.com", "evil-linkedin.com", False),
    ("linkedin.com", "linkedin.com.evil.test", False),
    ("www.linkedin.com", "linkedin.com", False),   # narrower grant, not broader
    ("linkedin.com", "", False),
    ("", "linkedin.com", False),
])
def test_a_grant_covers_subdomains_and_nothing_that_merely_looks_like_one(
        granted, host, expected):
    assert origins.covers(granted, host) is expected


# ── the decision ────────────────────────────────────────────────────────
def test_nothing_is_reachable_before_anything_is_granted():
    """There are no default grants. The user points at a site, the same consent
    gesture the Connectors panel already uses."""
    verdict = origins.may_read("https://linkedin.com/feed")

    assert verdict.allowed is False
    assert "not a site you have allowed" in verdict.reason


def test_a_granted_site_is_readable_including_its_subdomains():
    origins.grant("linkedin.com")

    assert origins.may_read("https://linkedin.com/feed").allowed
    assert origins.may_read("https://www.linkedin.com/messaging").allowed


def test_a_refusal_names_the_site_so_the_user_can_allow_that_one():
    """`grantable` exists so the UI offers the exact site instead of asking
    somebody to retype a hostname from a sentence."""
    verdict = origins.may_read("https://payroll.example.com/payslips")

    assert verdict.grantable == "https://payroll.example.com"
    assert "payroll.example.com" in verdict.reason


def test_an_address_no_grant_could_fix_offers_no_button():
    """A control that cannot work must not be shown. No grant makes
    `javascript:` reachable, so there is nothing to offer."""
    verdict = origins.may_read("javascript:alert(1)")

    assert verdict.allowed is False
    assert verdict.grantable is None


def test_revoking_takes_the_access_away_immediately():
    origins.grant("linkedin.com")
    assert origins.may_read("https://linkedin.com").allowed

    assert origins.revoke("https://LinkedIn.com/feed") is True

    assert origins.may_read("https://linkedin.com").allowed is False


def test_revoking_something_unparseable_is_false_not_an_exception():
    """Called from a UI with whatever is in a text field."""
    assert origins.revoke("¯\\_(ツ)_/¯") is False


def test_reading_can_be_turned_off_without_removing_the_site():
    origins.grant("linkedin.com", may_read=False)

    verdict = origins.may_read("https://linkedin.com")

    assert verdict.allowed is False
    assert "reading is turned off" in verdict.reason


# ── acting is a separate, closed door ───────────────────────────────────
def test_a_grant_does_not_include_acting():
    """The read-only landing must not quietly be a write-capable one."""
    origins.grant("amazon.co.uk")

    assert origins.may_read("https://amazon.co.uk/orders").allowed is True
    assert origins.may_act("https://amazon.co.uk/orders").allowed is False


def test_acting_on_an_ungranted_site_fails_for_the_read_reason_first():
    """The user should be told the site is not allowed at all, not that it is
    allowed but not for this — the second is a more confusing lie."""
    verdict = origins.may_act("https://amazon.co.uk/orders")

    assert verdict.allowed is False
    assert "not a site you have allowed" in verdict.reason


def test_acting_is_possible_to_grant_but_is_never_the_default():
    origins.grant("amazon.co.uk", may_act=True)

    assert origins.may_act("https://amazon.co.uk/orders").allowed is True
    # And the default really is closed:
    origins.grant("other.example.com")
    assert origins.may_act("https://other.example.com").allowed is False


# ── the most specific grant wins ────────────────────────────────────────
def test_a_specific_grant_is_not_shadowed_by_a_broader_one():
    """Somebody who granted both meant the narrower one to apply where it
    matches, or they would not have added it."""
    origins.grant("example.com", may_act=True)
    origins.grant("mail.example.com", may_act=False)

    assert origins.may_act("https://mail.example.com/inbox").allowed is False
    assert origins.may_act("https://shop.example.com").allowed is True


def test_granting_twice_updates_rather_than_duplicates():
    origins.grant("linkedin.com", note="first")
    origins.grant("linkedin.com", note="second")

    listed = origins.list_grants()

    assert len(listed) == 1
    assert listed[0].note == "second"


def test_grants_are_listed_by_host_so_the_panel_is_stable():
    for host in ("zulip.example.com", "amazon.co.uk", "mail.example.com"):
        origins.grant(host)

    assert [g.host for g in origins.list_grants()] == [
        "amazon.co.uk", "mail.example.com", "zulip.example.com"]


def test_a_bad_address_cannot_be_granted_at_all():
    """The boundary is only as good as what gets into the table."""
    for bad in ("http://linkedin.com", "javascript:alert(1)", "localhost"):
        with pytest.raises(BadOriginError):
            origins.grant(bad)

    assert origins.list_grants() == []
