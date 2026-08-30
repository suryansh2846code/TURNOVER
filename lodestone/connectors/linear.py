"""Linear connector — ingests your issues via the Linear GraphQL API.

Single-token auth: a Linear personal API key (Settings → API → Personal keys).
Declared as a `secret_field`, so the UI renders an in-app field — no .env.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..config import get_settings
from .base import Connector, SyncResult

API = "https://api.linear.app/graphql"
QUERY = """
{ issues(first: %d, orderBy: updatedAt) { nodes {
    identifier title description
    state { name } priorityLabel
    team { name } assignee { name } updatedAt
} } }
"""


class LinearConnector(Connector):
    name = "linear"
    label = "Linear"
    secret_field = {
        "key": "LINEAR_API_KEY",
        "label": "Linear personal API key",
        "placeholder": "lin_api_…",
        "help_url": "https://linear.app/settings/api",
        "steps": [
            "Open Linear → <b>Settings → API → Personal API keys</b> → "
            "<b>Create key</b>, then copy it.",
            "Paste it below and click Save.",
        ],
    }

    def is_configured(self) -> tuple[bool, str]:
        if get_settings().get_secret("LINEAR_API_KEY"):
            return True, ""
        return False, "click setup to paste your Linear API key"

    def sync(self, *, max_issues: int = 200, **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        key = get_settings().get_secret("LINEAR_API_KEY")
        if not key:
            result.errors.append("Linear API key not set")
            return self._finish(result)
        try:
            req = urllib.request.Request(
                API, data=(QUERY % max_issues).encode(),
                headers={"Authorization": key, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            nodes = (data.get("data") or {}).get("issues", {}).get("nodes", [])
            from ..brain import get_brain
            brain = get_brain()
            for it in nodes:
                title = f"{it['identifier']}: {it['title']}"
                text = (
                    f"Linear issue {title}\n"
                    f"Status: {(it.get('state') or {}).get('name', '?')}"
                    f" · Priority: {it.get('priorityLabel') or '—'}"
                    f" · Team: {(it.get('team') or {}).get('name', '?')}"
                    f" · Assignee: {(it.get('assignee') or {}).get('name', 'unassigned')}"
                    + (f"\n\n{it['description']}" if it.get("description") else "")
                )
                out = brain.ingest(text, source=self.name, kind="issue",
                                   title=title, fast=True,
                                   uri=f"https://linear.app/issue/{it['identifier']}")
                result.added += out["memories"]
                if not out["memories"]:
                    result.skipped += 1
            result.detail = f"{len(nodes)} issues"
        except urllib.error.HTTPError as exc:
            result.errors.append(
                "invalid Linear API key" if exc.code in (400, 401)
                else f"Linear API error {exc.code}")
            result.detail = "sync failed"
        except Exception as exc:
            result.errors.append(str(exc))
            result.detail = "sync failed"
        return self._finish(result)
