"""Turning an MCP server's failure into a sentence the user can act on.

A connector backed by someone else's subprocess fails in ways the vendor APIs
do not: the binary is gone, the runtime that launches it is not installed, the
process dies during the handshake, or it simply never answers. Each of those has
an obvious next step for the user and no obvious next step at all if what
reaches them is a traceback.

This deliberately mirrors `models/errors.py` rather than re-deriving it — same
rule ("never surface an internal"), same shape, just a different set of failures
because a subprocess is not an HTTP endpoint. Where the taxonomy already has an
answer, the message says the same thing it says for a vendor CLI.
"""
from __future__ import annotations

import asyncio

from ..models.errors import redact

#: What a cancelled scope leaves behind in a group — never the interesting
#: half. Named directly rather than via `anyio.get_cancelled_exc_class()`,
#: which needs a running loop and so cannot be called at import time.
_CANCELLED = (asyncio.CancelledError, GeneratorExit)

#: What to suggest when the server's own words are unrecognisable. Never a
#: traceback, and never the raw stderr — that is the vendor's debugging output,
#: not an instruction to a person.
_FALLBACK = ("{label} did not respond as expected. Check it in "
             "Connectors, or remove and re-add it.")

_AUTH_HINTS = ("unauthorized", "unauthenticated", "not logged in", "authenticat",
               "sign in", "log in", "login required", "invalid token",
               "invalid api key", "forbidden", "401", "403")
_MISSING_HINTS = ("no such file", "not found", "enoent", "command not found",
                  "is not recognized", "cannot find")
_RUNTIME_HINTS = ("npx", "node:", "python: can't open", "modulenotfounderror",
                  "cannot find module")
_TIMEOUT_HINTS = ("timeout", "timed out", "deadline")
#: A remote server's sign-in, as distinct from a stale credential: the user has
#: to finish something in a browser, which is a different next step from
#: "sign in again".
_CONSENT_HINTS = ("oauthflow", "oauth flow", "registration failed",
                  "did not return a code", "sign-in cancelled",
                  "invalid_client", "invalid_grant")
_NETWORK_HINTS = ("connection refused", "network", "dns", "getaddrinfo",
                  "unreachable", "ssl")
#: The server started and then stopped before it finished saying hello. Almost
#: always a setting it needed and did not get — a folder to read, a workspace
#: id — which is a different problem from "it is not installed" and has a
#: different next step.
_EXITED_HINTS = ("connection closed", "broken pipe", "eof",
                 "server process exited", "closed the connection")


def leaves(exc: BaseException) -> list[BaseException]:
    """The real failures inside an `ExceptionGroup`, flattened.

    Everything in the MCP client runs under an anyio task group, so what
    reaches a caller is an `ExceptionGroup` whose `str()` is the immortal
    "unhandled errors in a TaskGroup (1 sub-exception)" — which matches none of
    the hints below and is not a sentence anybody can act on. Worse, the groups
    nest, so one level of unwrapping is not enough.

    Without this, *every* connector failure reported the same fallback: a
    missing binary, a revoked token and a crashed server were one message.
    """
    if isinstance(exc, BaseExceptionGroup):
        out: list[BaseException] = []
        for inner in exc.exceptions:
            out.extend(leaves(inner))
        return out
    return [exc]


def explain(exc: BaseException, label: str) -> str:
    """One actionable sentence about why `label` could not be used.

    Takes the exception rather than a string so the caller cannot accidentally
    hand a formatted traceback straight through — the redaction and the
    truncation happen here, once.
    """
    found = leaves(exc)
    # The most specific leaf wins. A group carrying both a cancellation and the
    # real cause should be explained by the cause, and cancellations are what
    # a timeout leaves behind everywhere.
    ranked = [e for e in found if not isinstance(e, _CANCELLED)] or found
    exc = ranked[0]
    text = redact(" ".join(f"{type(e).__name__}: {e}" for e in ranked)).lower()

    if isinstance(exc, FileNotFoundError) or any(h in text for h in _MISSING_HINTS):
        if any(h in text for h in _RUNTIME_HINTS):
            return (f"{label} needs a runtime that isn't installed on this Mac. "
                    "Install it, then try connecting again.")
        return (f"{label} could not be started — the program it runs is missing. "
                "Reinstall it from Connectors.")
    if any(h in text for h in _CONSENT_HINTS):
        return (f"{label} didn't finish signing in. Open it in Connectors and "
                "choose Connect again — the sign-in happens on "
                f"{label}'s own site.")
    if any(h in text for h in _AUTH_HINTS):
        return (f"{label} isn't signed in. Open it in Connectors and sign in "
                "again — the sign-in happens with {vendor}, not with Lodestone."
                .replace("{vendor}", label))
    if any(h in text for h in _TIMEOUT_HINTS):
        return (f"{label} took too long to answer and was stopped. "
                "It may be busy — try again in a moment.")
    if any(h in text for h in _NETWORK_HINTS):
        return f"{label} couldn't reach its service. Check your connection."
    if any(h in text for h in _EXITED_HINTS):
        return (f"{label} stopped as soon as it started. It's usually missing a "
                "setting — remove it in Connectors and add it again.")
    if isinstance(exc, PermissionError):
        return (f"macOS blocked {label} from running. Allow it in System "
                "Settings → Privacy & Security, then try again.")
    return _FALLBACK.format(label=label)
