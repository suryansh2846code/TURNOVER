"""Custom API connector — let any user connect any REST app, no code.

A user describes an app in the UI (base URL, endpoint, auth, and which JSON
fields become the title/body). Definitions live in ~/Library/Lodestone/
custom_apps.json; the auth token (if any) lives in the chmod-600 secrets store.
Lodestone fetches the endpoint, walks to the list of items, and ingests each
into the brain — so custom apps behave exactly like the built-in connectors.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from ..config import get_settings
from .base import Connector, SyncResult

_APPS_FILE = "custom_apps.json"


# ── definition storage ────────────────────────────────────────────────────
def _apps_path():
    return get_settings().home / _APPS_FILE


def _load() -> dict[str, dict]:
    try:
        return json.loads(_apps_path().read_text())
    except Exception:
        return {}


def _save(apps: dict[str, dict]) -> None:
    get_settings().ensure_home()
    _apps_path().write_text(json.dumps(apps, indent=2))


def _secret_key(app_id: str) -> str:
    return f"CUSTOM_{app_id}_TOKEN"


def list_apps() -> list[dict]:
    return list(_load().values())


def get_app(app_id: str) -> dict | None:
    return _load().get(app_id)


def upsert_app(cfg: dict, token: str | None = None) -> dict:
    """Create or update a custom app. Returns the stored (token-free) config."""
    apps = _load()
    app_id = cfg.get("id") or f"{_slug(cfg.get('name', 'app'))}-{uuid.uuid4().hex[:6]}"
    stored = {
        "id": app_id,
        "name": cfg.get("name") or "Custom app",
        "base_url": (cfg.get("base_url") or "").rstrip("/"),
        "endpoint": cfg.get("endpoint") or "",
        "auth_type": cfg.get("auth_type") or "none",   # none|bearer|header|query
        "auth_name": cfg.get("auth_name") or "",       # header/query param name
        "items_path": cfg.get("items_path") or "",     # dot-path to the list
        "title_field": cfg.get("title_field") or "",
        "body_field": cfg.get("body_field") or "",
    }
    apps[app_id] = stored
    _save(apps)
    if token is not None:
        get_settings().set_secret(_secret_key(app_id), token)
    return stored


def delete_app(app_id: str) -> bool:
    apps = _load()
    if app_id not in apps:
        return False
    del apps[app_id]
    _save(apps)
    get_settings().set_secret(_secret_key(app_id), "")   # clear token too
    return True


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "app"


def _dig(obj: Any, path: str) -> Any:
    """Walk a dot-path (e.g. 'data.items') into nested dicts."""
    if not path:
        return obj
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


# ── the connector ─────────────────────────────────────────────────────────
class CustomAPIConnector(Connector):
    """Instantiated per custom-app definition (name = 'custom:<id>')."""

    def __init__(self, app: dict, store=None) -> None:
        super().__init__(store)
        self.app = app
        self.name = f"custom:{app['id']}"
        self.label = app.get("name") or "Custom app"

    def is_configured(self) -> tuple[bool, str]:
        if not self.app.get("base_url"):
            return False, "click setup to finish configuring this app"
        if self.app.get("auth_type", "none") != "none" and \
                not get_settings().get_secret(_secret_key(self.app["id"])):
            return False, "click setup to add this app's token"
        return True, ""

    def _request(self) -> Any:
        app = self.app
        url = app["base_url"] + (app.get("endpoint") or "")
        headers = {"Accept": "application/json", "User-Agent": "Lodestone"}
        token = get_settings().get_secret(_secret_key(app["id"]))
        atype = app.get("auth_type", "none")
        if token and atype == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        elif token and atype == "header":
            headers[app.get("auth_name") or "Authorization"] = token
        elif token and atype == "query":
            sep = "&" if "?" in url else "?"
            url += f"{sep}{urllib.parse.quote(app.get('auth_name') or 'api_key')}=" \
                   f"{urllib.parse.quote(token)}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def sync(self, *, max_items: int = 300, **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        ready, reason = self.is_configured()
        if not ready:
            result.errors.append(reason)
            return self._finish(result)
        try:
            data = self._request()
            items = _dig(data, self.app.get("items_path", ""))
            if isinstance(items, dict):        # single object → wrap
                items = [items]
            if not isinstance(items, list):
                result.errors.append(
                    "no list found — check 'items path' (e.g. data.results)")
                result.detail = "sync failed"
                return self._finish(result)

            from ..brain import get_brain
            brain = get_brain()
            tf, bf = self.app.get("title_field"), self.app.get("body_field")
            for it in items[:max_items]:
                if not isinstance(it, dict):
                    it = {"value": it}
                # Missing field → None; str(None) is "None" (truthy), so guard
                # explicitly rather than relying on `or` fallback, else field-less
                # records all collapse to an identical "None" and get deduped away.
                tval = _dig(it, tf) if tf else None
                bval = _dig(it, bf) if bf else None
                title = str(tval) if tval is not None else self.label
                body = (str(bval) if bval is not None
                        else json.dumps(it, ensure_ascii=False)[:2000])
                text = f"{self.label} — {title}\n\n{body}"
                out = brain.ingest(text, source=self.name, kind="record",
                                   title=title, fast=True)
                result.added += out["memories"]
                if not out["memories"]:
                    result.skipped += 1
            result.detail = f"{len(items)} records from {self.label}"
        except urllib.error.HTTPError as exc:
            result.errors.append(
                "auth failed — check the token" if exc.code in (401, 403)
                else f"API error {exc.code}")
            result.detail = "sync failed"
        except Exception as exc:
            result.errors.append(str(exc))
            result.detail = "sync failed"
        return self._finish(result)
