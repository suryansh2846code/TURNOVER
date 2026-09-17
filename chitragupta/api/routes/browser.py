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

from ...browser import chromium, origins
from ...log import get_logger

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
def forget_site(host: str):
    """Stop agents reading a site. Takes effect on the next call, not the next
    launch — anything the user can grant they can take back."""
    return {"revoked": origins.revoke(host)}


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
