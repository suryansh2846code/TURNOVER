"""Connected sources, the custom-app builder, and Google's own sign-in."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...brain import get_brain
from ...config import get_settings
from ...connectors import REGISTRY, get_connector
from ...log import get_logger, suppressed
from ..concurrency import probes_a_provider
from ..schemas import SecretIn

log = get_logger(__name__)
router = APIRouter()


class SyncIn(BaseModel):
    params: dict[str, Any] = {}


@router.get("/api/connectors")
@probes_a_provider
def connectors():
    brain = get_brain()
    state = brain.store.all_connector_state()
    out = []
    for name, cls in REGISTRY.items():
        if not cls.supported_here():
            continue                      # hide macOS-only connectors off macOS
        inst = cls()
        ready, reason = inst.is_configured()
        out.append({"name": name, "label": cls.label, "ready": ready,
                    "reason": reason, "always_available": cls.always_available,
                    "secret_field": cls.secret_field, "custom": False,
                    "state": state.get(name)})
    # user-defined custom API apps
    from ...connectors.custom_api import CustomAPIConnector, list_apps
    for app in list_apps():
        inst = CustomAPIConnector(app)
        ready, reason = inst.is_configured()
        out.append({"name": inst.name, "label": inst.label, "ready": ready,
                    "reason": reason, "always_available": False,
                    "secret_field": None, "custom": True, "config": app,
                    "state": state.get(inst.name)})
    # MCP-backed connectors, one per server the user added. `is_configured()`
    # starts the server, which is the only honest test of "can this run" — but
    # it is also why this endpoint is in the probe lane.
    from ...connectors.mcp_source import MCPConnector, list_servers
    for spec in list_servers():
        inst = MCPConnector(spec)
        ready, reason = inst.is_configured()
        out.append({"name": inst.name, "label": inst.label, "ready": ready,
                    "reason": reason, "always_available": False,
                    "secret_field": None, "custom": False, "mcp": True,
                    "config": spec.as_dict(), "state": state.get(inst.name)})
    return {"connectors": out}


# ── the connector catalog (MCP-backed sources) ────────────────────────────


@router.get("/api/connectors/catalog")
def connector_catalog() -> dict[str, Any]:
    """What can be added, and what cannot — with the reason either way.

    Blocked sources are returned rather than omitted: a grid that silently
    lacks LinkedIn teaches the user the app is missing a feature, when the
    truth is that no app can offer it. "Never show a control that cannot work"
    means saying so where the control would have been.
    """
    from ...connectors.mcp_catalog import BLOCKED, CATALOG
    from ...connectors.mcp_source import list_servers

    added = {spec.id for spec in list_servers()}
    return {
        "available": [{"id": e.id, "name": e.name, "notes": e.notes,
                       "first_party": e.first_party, "added": e.id in added,
                       "needs_env": [{"name": n, "help": h} for n, h in e.needs_env]}
                      for e in CATALOG],
        "blocked": [{"id": b.id, "name": b.name, "reason": b.reason}
                    for b in BLOCKED],
    }


class CatalogAddIn(BaseModel):
    env: dict[str, str] = {}


@router.post("/api/connectors/catalog/{entry_id}")
@probes_a_provider
def connector_catalog_add(entry_id: str, body: CatalogAddIn) -> dict[str, Any]:
    """Add a catalog connector, after verifying it actually runs.

    Returns `ok: False` with a reason rather than raising, so the form can say
    what happened in place instead of showing a failed request.
    """
    from ...connectors.mcp_catalog import add_from_catalog

    spec, reason = add_from_catalog(entry_id, body.env)
    if spec is None:
        return {"ok": False, "error": reason}
    return {"ok": True, "name": f"mcp:{spec.id}", "label": spec.name}


@router.get("/api/connectors/catalog/{entry_id}/permissions")
@probes_a_provider
def connector_permissions(entry_id: str) -> dict[str, Any]:
    """What this connector would be able to read and change, before enabling.

    Consent to something nobody has been shown is not consent.
    """
    from ...connectors.mcp_catalog import describe

    return describe(entry_id)


@router.delete("/api/connectors/mcp/{server_id}")
def connector_mcp_delete(server_id: str) -> dict[str, Any]:
    from ...connectors.mcp_source import delete_server

    return {"ok": delete_server(server_id)}


# ── custom apps (connect any REST app, no code) ───────────────────────────
class CustomAppIn(BaseModel):
    id: str | None = None
    name: str = "Custom app"
    base_url: str = ""
    endpoint: str = ""
    auth_type: str = "none"      # none | bearer | header | query
    auth_name: str = ""
    token: str | None = None
    items_path: str = ""
    title_field: str = ""
    body_field: str = ""


@router.get("/api/custom-apps")
def custom_apps():
    from ...connectors.custom_api import list_apps
    return {"apps": list_apps()}


@router.post("/api/custom-apps")
def save_custom_app(body: CustomAppIn):
    from ...connectors.custom_api import upsert_app
    url = (body.base_url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(422, "base URL must start with http:// or https://")
    cfg = body.model_dump()
    token = cfg.pop("token", None)
    app = upsert_app(cfg, token=token)
    return {"saved": True, "app": app, "name": f"custom:{app['id']}"}


@router.delete("/api/custom-apps/{app_id}")
def delete_custom_app(app_id: str):
    from ...connectors.custom_api import delete_app
    return {"deleted": delete_app(app_id)}


@router.post("/api/connectors/{name}/secret")
def save_connector_secret(name: str, body: SecretIn):
    """Save (or clear) a connector's single-token secret from the UI —
    no .env editing. Written to ~/Library/Lodestone/secrets.json (chmod 600)."""
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise HTTPException(404, f"unknown connector '{name}'") from None
    field = cls.secret_field
    if not field:
        raise HTTPException(400, f"'{name}' does not use a token secret")
    get_settings().set_secret(field["key"], body.value)
    ready, reason = cls().is_configured()
    return {"saved": True, "ready": ready, "reason": reason}


@router.post("/api/connectors/{name}/sync")
@probes_a_provider
def sync(name: str, body: SyncIn):
    try:
        conn = get_connector(name)
    except KeyError:
        raise HTTPException(404, f"unknown connector '{name}'") from None
    # route ingestion through the brain so the graph is built too
    res = conn.sync(**body.params)
    return res.as_dict()


# ── Google sign-in (bundled client → no per-user Cloud setup) ─────────────
class MCPActionIn(BaseModel):
    """A write the user has looked at and approved.

    `confirmed` is carried explicitly rather than implied by the request: a
    connector action changes something in the user's account, and "they called
    the endpoint" is not the same as "they were shown what it would do".
    """

    tool: str
    arguments: dict[str, Any] = {}
    confirmed: bool = False


def _mcp(server_id: str):
    """The MCP connector for this id, or a 404.

    Returns the concrete type rather than the `Connector` base: `perform()` is
    the one path in the whole connector layer that changes something at a
    vendor, and a route that reached it through a duck-typed base could be
    pointed at anything that happened to grow the method.
    """
    from ...connectors.mcp_source import MCPConnector

    try:
        conn = get_connector(f"mcp:{server_id}")
    except KeyError:
        raise HTTPException(404, "That connector is not set up.") from None
    if not isinstance(conn, MCPConnector):       # pragma: no cover - unreachable
        raise HTTPException(404, "That connector is not set up.")
    return conn


@router.get("/api/connectors/mcp/{server_id}/actions")
@probes_a_provider
def mcp_actions(server_id: str) -> dict[str, Any]:
    """What this connector could change, so a card can ask before it does."""
    return {"actions": _mcp(server_id).available_actions()}


@router.post("/api/connectors/mcp/{server_id}/action")
@probes_a_provider
def mcp_action(server_id: str, body: MCPActionIn) -> dict[str, Any]:
    """Run a confirmed action. Refuses, rather than runs, when unconfirmed."""
    return _mcp(server_id).perform(body.tool, body.arguments,
                                   confirmed=body.confirmed)


@router.get("/api/google/status")
@probes_a_provider
def google_status():
    from ...connectors.google_auth import _token_path, connected_email, granted_services
    connected = _token_path().exists()
    account = connected_email(fetch=connected) if connected else None
    return {"client_configured": get_settings().google_client_secrets is not None,
            "connected": connected,
            "account": account,
            "services": granted_services()}


@router.post("/api/google/disconnect")
def google_disconnect():
    from ...connectors.google_auth import disconnect
    disconnect()
    return {"disconnected": True}


# ── Google reconnect (re-consent with current scopes, from the UI) ────────
@router.post("/api/google/reconnect")
@probes_a_provider
def google_reconnect():
    import threading

    from ...connectors.google_auth import _token_path, connected_email, get_credentials
    tok = _token_path()
    if tok.exists():
        tok.unlink()

    def _run():
        with suppressed("get_credentials(interactive=True) …"):
            get_credentials(interactive=True)
            connected_email(fetch=True)

    # opens the Google consent browser on this machine; runs in the background
    threading.Thread(target=_run, daemon=True).start()
    return {"started": True,
            "detail": "A browser window is opening — approve the permissions."}
