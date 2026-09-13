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

from ..models.errors import redact

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
_NETWORK_HINTS = ("connection refused", "network", "dns", "getaddrinfo",
                  "unreachable", "ssl")


def explain(exc: BaseException, label: str) -> str:
    """One actionable sentence about why `label` could not be used.

    Takes the exception rather than a string so the caller cannot accidentally
    hand a formatted traceback straight through — the redaction and the
    truncation happen here, once.
    """
    text = redact(f"{type(exc).__name__}: {exc}").lower()

    if isinstance(exc, FileNotFoundError) or any(h in text for h in _MISSING_HINTS):
        if any(h in text for h in _RUNTIME_HINTS):
            return (f"{label} needs a runtime that isn't installed on this Mac. "
                    "Install it, then try connecting again.")
        return (f"{label} could not be started — the program it runs is missing. "
                "Reinstall it from Connectors.")
    if any(h in text for h in _AUTH_HINTS):
        return (f"{label} isn't signed in. Open it in Connectors and sign in "
                "again — the sign-in happens with {vendor}, not with Lodestone."
                .replace("{vendor}", label))
    if any(h in text for h in _TIMEOUT_HINTS):
        return (f"{label} took too long to answer and was stopped. "
                "It may be busy — try again in a moment.")
    if any(h in text for h in _NETWORK_HINTS):
        return f"{label} couldn't reach its service. Check your connection."
    if isinstance(exc, PermissionError):
        return (f"macOS blocked {label} from running. Allow it in System "
                "Settings → Privacy & Security, then try again.")
    return _FALLBACK.format(label=label)
