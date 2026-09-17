"""Websites agents may read, and the browser that reads them.

The allow-list is the whole consent model for the most dangerous capability in
the app, so it needs a place a person can actually see it. `docs/BROWSER.md`
argues that place is next to the connectors: *"a logged-in site is a connection,
and the Connectors panel must say so"* — anything else and there is no single
screen that answers "what can this app reach on my behalf".

Two things this surface is careful about.

**A site is added by a person, never by an agent.** No tool reaches these
routes; `agents/browse_tools.py` has no path into `origins.grant`. An agent that
has been talked into wanting more access can report which site it would need and
nothing else, which is what keeps the list from being decorative.

**A refusal names the site it would take.** `origins.may_read` returns a
`grantable` origin, so the UI offers the exact site rather than asking somebody
to retype a hostname out of a sentence — the same shape as the "Always allow"
button on an approval card.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...browser import chromium, origins, signin
from ...log import get_logger
from ..concurrency import probes_a_provider

log = get_logger(__name__)
router = APIRouter()


class SiteIn(BaseModel):
    """A site the user is allowing. `url` may be a bare host — the grant field
    is typed by a person, and `https://` is not something to make them write."""

    url: str
    note: str = ""


@router.get("/api/browser/status")
def browser_status():
    """Everything the panel needs in one poll: setup state and the site list."""
    return {**chromium.install_status(),
            "sites": [g.as_dict() for g in origins.list_grants()]}


@router.get("/api/browser/sites")
def list_sites():
    return {"sites": [g.as_dict() for g in origins.list_grants()]}


@router.post("/api/browser/sites")
def allow_site(body: SiteIn):
    """Allow agents to read a site.

    Reading only: `may_act` is not settable from here, because acting is a
    separate landing with an approval card and a grant that quietly included it
    would make the read-only ship a write-capable one.
    """
    try:
        granted = origins.grant(body.url, note=body.note)
    except origins.BadOriginError as exc:
        # The message is written for a person — "only https addresses can be
        # used" rather than a validation code.
        raise HTTPException(400, str(exc)) from None
    return granted.as_dict()


@router.delete("/api/browser/sites/{host}")
@probes_a_provider
def forget_site(host: str):
    """Disconnect a site: the permission AND the sign-in.

    Takes effect on the next call, not the next launch — anything the user can
    grant they can take back.

    Dropping the grant alone would leave the user signed in with a cookie jar
    that outlives the permission, which is a lie about what Disconnect did. The
    cookies go too, so reconnecting means signing in again.
    """
    revoked = origins.revoke(host)
    return {"revoked": revoked, "signed_out": chromium.forget_site(host)}


# ── connecting a site: the user signs in once, here ──────────────────────
#
# Four endpoints rather than one, because signing in is not one moment. A window
# opens, a person does something we cannot see or hurry — a password, a code
# from their phone, a CAPTCHA — and only they know when it is done. Each step
# returns the same `{ok, error, detail}` shape so the card driving it never has
# to tell them apart.
#
# Contract: docs/development/connected-sites.md
class ConnectIn(BaseModel):
    """Which site to open for signing in."""

    url: str


class FinishIn(BaseModel):
    """Done signing in.

    `force` is the user overriding our guess. The sign-in heuristic will be
    wrong on some site, and a person who cannot say "I really am signed in" is
    one we have locked out of their own account.
    """

    force: bool = False


@router.get("/api/browser/connect")
def connect_status():
    """Whether a sign-in is in progress, and what it is waiting on."""
    return signin.status()


@router.post("/api/browser/connect")
@probes_a_provider
def connect_begin(body: ConnectIn):
    """Open the browser at a site so the user can sign in.

    Grants nothing. A window being open is not consent, and a user who thinks
    better of it should leave no trace behind.
    """
    return signin.begin(body.url)


@router.post("/api/browser/connect/finish")
@probes_a_provider
def connect_finish(body: FinishIn):
    """Record the connection, once the user says they are signed in."""
    return signin.finish(force=body.force)


@router.post("/api/browser/connect/cancel")
@probes_a_provider
def connect_cancel():
    """Give up on a sign-in. Nothing is granted and nothing is remembered."""
    return signin.cancel()


@router.post("/api/browser/install")
def install_browser():
    """Begin the one-time browser download. Poll `/api/browser/status`."""
    return chromium.install_status() if chromium.is_installed() \
        else chromium.start_install()


@router.post("/api/browser/forget-everything")
def forget_everything():
    """Delete the profile: every sign-in the user made inside the app.

    The heavy half of "sign-out is a real control", and deliberately not the same
    button as removing the browser — one is about disk space and the other is
    about access.
    """
    return {"forgotten": chromium.forget_everything()}
