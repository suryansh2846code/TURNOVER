"""Signing in to a remote connector, without Chitragupta owning an OAuth client.

A remote MCP server is the vendor's own endpoint. Reaching it needs the user's
own token, and getting one normally means registering as a developer with that
vendor and waiting for approval — per vendor, which is exactly the wall that
makes hand-written connectors stop at about six.

**Dynamic Client Registration (RFC 7591) removes that wall.** The app
introduces itself at the moment of connecting, the consent screen carries the
*vendor's* name, and we register nothing in advance. It is the same property
that made a local stdio server attractive — "we register no OAuth client and
need no verification" — reached without running a third party's code as the
user with access to their credentials.

Three things this module owns, and nothing else does:

* **Where the tokens live.** The Keychain, through the same `set_secret` /
  `get_secret` the rest of the app uses. Never the spec file, which is served
  to the page by `GET /api/connectors`.
* **How consent happens.** The vendor's page in the user's real browser, with
  the redirect caught by a one-shot loopback server on an ephemeral port. Not
  the app's own port: that one is user state (`docs/DESKTOP-SIGNIN.md`) and
  binding a second listener to it is how the saved-port invariant gets broken.
* **What the UI is allowed to know.** A status, a label and a reason — never a
  token, never a URL with a code in it.

Anything the user starts here, they can stop: `cancel()` unblocks the waiting
flow and the loopback listener closes with it.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import get_settings
from ..log import get_logger, suppressed

log = get_logger(__name__)

#: How long the user has to finish a vendor's consent screen before we stop
#: waiting. Generous — it can mean finding a password, or a second factor on a
#: phone — but finite, because a listener nobody will ever talk to is a leak.
CONSENT_TIMEOUT_SECONDS = 300.0

#: What we tell a vendor about ourselves at registration time. Every identifier
#: here is ours: sending somebody else's would make our users' sign-in
#: breakable by a decision we do not control (`/CLAUDE.md`, models invariants).
CLIENT_NAME = "Chitragupta"
CLIENT_URI = "https://chitragupta.app"


class _NeedsSignInError(RuntimeError):
    """Raised instead of opening a browser on a path nobody asked to sign in on."""

    def __init__(self, label: str) -> None:
        super().__init__(f"{label} needs you to sign in")
        self.label = label


def _quiet_expected_refusals() -> None:
    """Stop the SDK logging a traceback for a refusal we asked for.

    Declining to open a browser on a background probe is the designed
    behaviour, and it happens on every Connectors load for a connector that is
    simply signed out. The SDK cannot know that and logs it at ERROR with a
    stack trace, which buries the failures that *are* worth reading.

    Narrow on purpose: one logger, one exception type. Everything else the
    OAuth client has to say still comes through.
    """
    import logging

    class _Filter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            exc = (record.exc_info or (None, None, None))[1]
            return not isinstance(exc, _NeedsSignInError)

    logging.getLogger("mcp.client.auth.oauth2").addFilter(_Filter())


_quiet_expected_refusals()


def _token_secret(server_id: str) -> str:
    return f"mcp-oauth:{server_id}:tokens"


def _client_secret(server_id: str) -> str:
    return f"mcp-oauth:{server_id}:client"


# ── token storage ───────────────────────────────────────────────────────────


class KeychainTokenStorage:
    """The SDK's `TokenStorage`, backed by the Keychain.

    Satisfied structurally rather than by inheritance — the SDK declares it as
    a `Protocol`, and importing the symbol at class-creation time would put an
    import of the MCP package on a path that must work without one.
    """

    def __init__(self, server_id: str) -> None:
        self.server_id = server_id

    # tokens ────────────────────────────────────────────────────────────
    async def get_tokens(self) -> Any | None:
        from mcp.shared.auth import OAuthToken

        raw = get_settings().get_secret(_token_secret(self.server_id))
        if not raw:
            return None
        with suppressed("reading a connector's stored sign-in"):
            return OAuthToken.model_validate_json(raw)
        return None

    async def set_tokens(self, tokens: Any) -> None:
        get_settings().set_secret(
            _token_secret(self.server_id), tokens.model_dump_json())

    # the registration this app was granted ─────────────────────────────
    async def get_client_info(self) -> Any | None:
        from mcp.shared.auth import OAuthClientInformationFull

        raw = get_settings().get_secret(_client_secret(self.server_id))
        if not raw:
            return None
        with suppressed("reading a connector's stored registration"):
            return OAuthClientInformationFull.model_validate_json(raw)
        return None

    async def set_client_info(self, client_info: Any) -> None:
        get_settings().set_secret(
            _client_secret(self.server_id), client_info.model_dump_json())


def forget_tokens(server_id: str) -> None:
    """Drop a server's sign-in and its registration.

    Called when a connector is removed. A token left behind would mean re-adding
    the connector silently reusing access the user believed they had revoked.
    """
    settings = get_settings()
    settings.set_secret(_token_secret(server_id), None)
    settings.set_secret(_client_secret(server_id), None)


def is_signed_in(server_id: str) -> bool:
    """Is there a stored token? Not whether it still works — that needs a call."""
    return bool(get_settings().get_secret(_token_secret(server_id)))


# ── the consent flow, and what the UI may see of it ─────────────────────────


@dataclass
class _Flow:
    """One sign-in in progress. Exactly one per server at a time."""

    server_id: str
    label: str
    status: str = "pending"          # pending | connected | failed | cancelled
    reason: str = ""
    auth_url: str = ""
    code: str = ""
    state: str = ""
    started_at: float = field(default_factory=time.monotonic)
    arrived: threading.Event = field(default_factory=threading.Event)


_flows: dict[str, _Flow] = {}
_lock = threading.Lock()


def status(server_id: str) -> dict[str, Any]:
    """What to show where the user is looking. Never a token, never a code."""
    with _lock:
        flow = _flows.get(server_id)
    if flow is None:
        return {"status": "connected" if is_signed_in(server_id) else "none",
                "reason": ""}
    return {"status": flow.status, "reason": flow.reason,
            "auth_url": flow.auth_url if flow.status == "pending" else ""}


def cancel(server_id: str) -> bool:
    """Stop a sign-in the user started. Anything they start, they can stop."""
    with _lock:
        flow = _flows.get(server_id)
    if flow is None or flow.status != "pending":
        return False
    flow.status = "cancelled"
    flow.reason = "Sign-in cancelled."
    flow.arrived.set()               # unblock the waiter so its listener closes
    return True


def _finish(server_id: str, status_value: str, reason: str = "") -> None:
    with _lock:
        flow = _flows.get(server_id)
    if flow is not None:
        flow.status = status_value
        flow.reason = reason


# ── the loopback listener that catches the redirect ─────────────────────────

_DONE_PAGE = b"""<!doctype html><meta charset="utf-8">
<title>Signed in</title>
<style>
 body{font:16px -apple-system,system-ui,sans-serif;background:#060810;color:#dfe7f2;
      display:grid;place-items:center;height:100vh;margin:0;text-align:center}
 p{color:#7a8397;margin-top:10px}
 b{color:#f5c877;font-weight:600}
</style>
<div><b>Connected.</b><p>You can close this tab and go back to Chitragupta.</p></div>
"""

_FAIL_PAGE = b"""<!doctype html><meta charset="utf-8">
<title>Not connected</title>
<style>
 body{font:16px -apple-system,system-ui,sans-serif;background:#060810;color:#dfe7f2;
      display:grid;place-items:center;height:100vh;margin:0;text-align:center}
 p{color:#7a8397;margin-top:10px}
 b{color:#e2705e;font-weight:600}
</style>
<div><b>That didn't complete.</b><p>Go back to Chitragupta and try connecting again.</p></div>
"""


def _listener(flow: _Flow) -> tuple[Any, int]:
    """A one-shot HTTP server on an ephemeral loopback port.

    Deliberately *not* the app's own port. That one is bound to the saved
    webview origin and is user state; a second listener on it is how the
    saved-port invariant in `docs/DESKTOP-SIGNIN.md` gets broken.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            code = (query.get("code") or [""])[0]
            error = (query.get("error") or [""])[0]
            flow.code = code
            flow.state = (query.get("state") or [""])[0]
            body = _DONE_PAGE if code and not error else _FAIL_PAGE
            if error:
                flow.reason = f"{flow.label} refused the sign-in."
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            flow.arrived.set()

        def log_message(self, *_: Any) -> None:
            """The stdlib default writes to stderr. Ours is a real log or none."""

    server = HTTPServer(("127.0.0.1", 0), Handler)
    return server, server.server_port


# ── the provider the transport actually uses ────────────────────────────────


def auth_provider(spec: Any, *, interactive: bool = False) -> Any:
    """The SDK's OAuth provider for one remote server.

    Handed straight to the HTTP client. When a stored token is present and
    valid this never opens anything.

    **`interactive` is False by default, and that default is load-bearing.**
    Reaching a remote server happens on paths nobody asked to sign in on — the
    Connectors page probes every connector on load, the scheduler syncs on a
    timer, an agent turn lists tools. If any of those could open a browser, a
    connector whose token had expired would hijack the user's screen while they
    were doing something else, and then hold the caller for the length of the
    consent timeout. A probe reports "needs signing in"; only the Connect
    button actually opens anything.
    """
    from mcp.client.auth.oauth2 import OAuthClientProvider
    from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata

    server_id, label = spec.id, spec.name

    with _lock:
        flow = _flows.get(server_id)
        if flow is None or flow.status != "pending":
            flow = _Flow(server_id=server_id, label=label)
            _flows[server_id] = flow

    # A listener is only worth opening when a browser may actually redirect to
    # it. On a probe the flow stops at `redirect_handler`, so binding a socket
    # here would leak one per page load.
    server, port = _listener(flow) if interactive else (None, 0)
    redirect_uri = f"http://127.0.0.1:{port or 1}/callback"

    async def redirect_handler(auth_url: str) -> None:
        """Send the user to the vendor's own consent screen.

        On a non-interactive path this refuses instead, which is what turns a
        hijacked browser and a five-minute stall into a sentence the
        Connectors page can show.
        """
        import webbrowser

        if not interactive:
            raise _NeedsSignInError(label)
        flow.auth_url = auth_url
        log.info("opening %s sign-in in the browser", label)
        with suppressed("opening the browser for a connector sign-in"):
            webbrowser.open(auth_url)

    async def callback_handler() -> AuthorizationCodeResult:
        """Wait for the redirect, then hand the code back to the SDK."""
        import anyio

        try:
            # `abandon_on_cancel` so an outer timeout can actually end this.
            # Without it the worker thread keeps waiting on the event and the
            # cancel scope cannot complete — a sign-in nobody finishes would
            # hold the caller for the whole consent window.
            arrived = await anyio.to_thread.run_sync(
                lambda: flow.arrived.wait(CONSENT_TIMEOUT_SECONDS),
                abandon_on_cancel=True)
        finally:
            if server is not None:
                with suppressed("closing the sign-in listener"):
                    server.server_close()

        if not arrived:
            _finish(server_id, "failed",
                    f"{label} sign-in timed out. Try connecting again.")
            raise TimeoutError(f"{label} sign-in timed out")
        if flow.status == "cancelled":
            raise RuntimeError(f"{label} sign-in cancelled")
        if not flow.code:
            _finish(server_id, "failed",
                    flow.reason or f"{label} did not complete the sign-in.")
            raise RuntimeError(f"{label} sign-in did not return a code")

        _finish(server_id, "connected")
        return AuthorizationCodeResult(code=flow.code, state=flow.state or None)

    metadata = OAuthClientMetadata(
        client_name=CLIENT_NAME,
        client_uri=CLIENT_URI,          # type: ignore[arg-type]  # pydantic coerces the str
        redirect_uris=[redirect_uri],          # type: ignore[list-item]
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",     # a desktop app keeps no secret
    )

    # Serving in a daemon thread rather than a blocking accept: the SDK calls
    # `redirect_handler` and `callback_handler` on its own loop, and the
    # listener has to already be accepting by the time the browser lands.
    if server is not None:
        threading.Thread(target=server.serve_forever,
                         kwargs={"poll_interval": 0.2}, daemon=True).start()

    return OAuthClientProvider(
        server_url=spec.url,
        client_metadata=metadata,
        storage=KeychainTokenStorage(server_id),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


def begin(spec: Any) -> dict[str, Any]:
    """Start a sign-in in the background and return immediately.

    The caller is an HTTP handler the UI is waiting on, so the browser trip
    cannot happen inside it. The flow's progress is read back through
    `status()`, which survives a refresh because it lives in this module rather
    than in the request.
    """
    from .mcp_source import probe

    with _lock:
        existing = _flows.get(spec.id)
        if existing is not None and existing.status == "pending":
            return {"started": False, "status": "pending",
                    "detail": f"A {spec.name} sign-in is already open."}
        _flows[spec.id] = _Flow(server_id=spec.id, label=spec.name)

    def run() -> None:
        # Probing *is* the sign-in: the first call to a protected endpoint is
        # what triggers the OAuth challenge the provider answers. This is the
        # one path that passes `interactive=True`, which is what allows a
        # browser to open at all.
        kinds, reason = probe(spec, interactive=True)
        if kinds is None:
            with _lock:
                flow = _flows.get(spec.id)
            if flow is not None and flow.status == "pending":
                _finish(spec.id, "failed", reason)
        else:
            _finish(spec.id, "connected")
            with suppressed("refreshing the tool list after a sign-in"):
                from .mcp_tools import invalidate

                invalidate()

    threading.Thread(target=run, daemon=True).start()
    return {"started": True, "status": "pending",
            "detail": f"A browser window is opening — sign in to {spec.name}."}


# ── telling "sign in" apart from "broken" ───────────────────────────────────


def challenge(url: str) -> bool:
    """Does this endpoint answer an unauthenticated call with an OAuth challenge?

    The MCP client raises a generic protocol error for an HTTP 401 — the status
    never reaches the exception — so "your token expired" and "the server is
    broken" arrive identical. One unauthenticated request on the failure path
    separates them, and `WWW-Authenticate` is the server's own answer rather
    than our guess.

    Only called when something already went wrong, so it costs nothing in the
    normal case.
    """
    import httpx2

    with suppressed("asking a connector whether it needs a sign-in"):
        reply = httpx2.post(
            url, timeout=8.0,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {}})
        if reply.status_code in (401, 403):
            return True
        return "www-authenticate" in {k.lower() for k in reply.headers}
    return False
