"""Origin guarding for the local HTTP server.

Lodestone's API is the user's machine in miniature: it lists their home
directory, stores provider credentials, and can erase the brain. It listens on
loopback with no authentication, which is ordinary for a local app and is
exactly why it needs a guard — *reachable only from this machine* is not the
same as *reachable only by this app*. Every browser the user has open is also
"on this machine".

Two attacks are real against a localhost server, and neither needs the attacker
to have any access to it:

* **DNS rebinding.** A page on `evil.com` whose DNS flips to `127.0.0.1` is,
  as far as the browser is concerned, same-origin with our server — so it can
  read every response, including saved credentials. The one thing the attacker
  cannot change is the `Host` header, which still says `evil.com`. Requiring a
  loopback `Host` ends the attack.
* **Cross-site request forgery.** Any page the user has open can POST to
  `http://127.0.0.1:8787/api/brain/reset` without ever reading the reply.
  Browsers attach `Origin` to cross-origin state-changing requests, so refusing
  a foreign `Origin` ends that one.

`Sec-Fetch-Site` is checked as well where the browser sends it, because it
states the browser's own conclusion rather than asking us to infer it.

**Same-origin is checked by comparing `Origin` to `Host`, not by asking whether
`Origin` is loopback.** The first version of this module accepted any loopback
origin, which is not the same question: a Vite dev server on `localhost:5173`, a
notebook on `localhost:8888` or any other local web app the user has open in a
tab *is* a loopback origin, and could therefore `POST /api/brain/reset` or read
`/api/fs/browse`. The browser is not free to lie about either header, and our own
page is by definition served from the authority the request arrived on — so
requiring them to match distinguishes our page from every other local origin
without needing to know our own port.

**Deliberately not a token.** Against a *process* on the machine a token buys
nothing: it would have to live somewhere every process running as the user can
read. Against a *browser* it would buy something — but only what the
`Origin`/`Host` comparison above already buys, and that needs nothing injected
into the page to work.
"""
from __future__ import annotations

from collections.abc import Mapping

# Hostnames that mean "this machine". A request addressed to anything else was
# addressed to somebody else and only reached us by trickery.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

# Methods that can change state. GETs are still Host-checked (rebinding reads
# are the whole point of rebinding); only these additionally require a local
# Origin, because a cross-site POST succeeds even when the reply is unreadable.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# What the browser is willing to tell us about who started the request.
_ALLOWED_FETCH_SITES = frozenset({"same-origin", "same-site", "none"})

_FOREIGN_SITE = "Lodestone ignores requests that come from a website."
_FOREIGN_HOST = "Lodestone ignores requests addressed to another machine."


def hostname_of(value: str) -> str:
    """The host part of a `Host`/authority value, with any port removed.

    Handles the bracketed IPv6 form (`[::1]:8787`) and a bare IPv6 literal,
    where splitting on the last colon would otherwise mangle the address.
    """
    raw = (value or "").strip().lower()
    if raw.startswith("["):                       # [::1]:8787 → [::1]
        end = raw.find("]")
        return raw[: end + 1] if end != -1 else raw
    if raw.count(":") > 1:                        # bare ::1 — no port to strip
        return raw
    return raw.split(":", 1)[0]


def is_loopback_host(value: str) -> bool:
    """Is this authority one of the names for this machine?"""
    return hostname_of(value) in LOOPBACK_HOSTS


def is_local_origin(origin: str) -> bool:
    """Is this `Origin` header one of our own pages?

    An opaque origin (`null` — a sandboxed iframe or a `file://` page) is not
    ours, and is treated as foreign rather than as missing.
    """
    raw = (origin or "").strip().lower()
    if not raw or raw == "null":
        return False
    authority = raw.split("://", 1)[1] if "://" in raw else raw
    return is_loopback_host(authority)


def same_origin(origin: str, host: str) -> bool:
    """Did this request come from the page we ourselves served?

    Compares authorities (host **and** port), because the port is the whole
    point: `localhost:3000` and `127.0.0.1:8787` are both loopback and are not
    each other. The scheme is ignored — we only ever serve plain HTTP on
    loopback, and a browser cannot reach us any other way.
    """
    if not is_local_origin(origin) or not is_loopback_host(host):
        return False
    authority = origin.strip().lower()
    if "://" in authority:
        authority = authority.split("://", 1)[1]
    return _authority(authority) == _authority(host)


def _authority(value: str) -> tuple[str, str]:
    """(host, port) — with the two spellings of "this machine" treated as one.

    A user who opens `http://localhost:8787` gets `localhost` in both headers and
    a user on `127.0.0.1:8787` gets that in both, so they always agree with
    themselves. Normalising means neither spelling is a special case.
    """
    raw = (value or "").strip().lower()
    name = hostname_of(raw)
    rest = raw[len(name):]
    port = rest[1:] if rest.startswith(":") else ""
    return ("loopback" if name in LOOPBACK_HOSTS else name, port)


def refusal(method: str, headers: Mapping[str, str]) -> str | None:
    """The reason this request must be refused, or None to let it through.

    Split out from the middleware so the policy can be tested as a function
    rather than only through a live server.
    """
    if not is_loopback_host(headers.get("host", "")):
        return _FOREIGN_HOST

    # The browser's own verdict, where it offers one. Absent for non-browser
    # callers (curl, the tests), so it can sharpen the check but never carry it.
    site = (headers.get("sec-fetch-site") or "").strip().lower()
    if site and site not in _ALLOWED_FETCH_SITES:
        return _FOREIGN_SITE

    # Our own page is served from the authority the request arrived on, so its
    # `Origin` always matches `Host`. Anything else — including another app on
    # another loopback port — does not.
    #
    # A request with no `Origin` at all is not refused here: that is a top-level
    # navigation, a non-browser caller, or a browser too old to send the header,
    # and the `Host` check above is what covers those.
    origin = headers.get("origin") or ""
    if origin and not same_origin(origin, headers.get("host", "")):
        return _FOREIGN_SITE
    return None


def is_safe_external_url(url: str) -> bool:
    """May we hand this URL to the system browser?

    `/api/open-browser` exists so a sign-in page can be opened for the user. It
    must not become a way to launch `file://`, `javascript:` or a custom scheme
    registered by some other installed app.
    """
    candidate = (url or "").strip()
    if not candidate or any(c in candidate for c in "\r\n\t"):
        return False
    scheme, _, rest = candidate.partition("://")
    return scheme.lower() in ("http", "https") and bool(rest.strip())
