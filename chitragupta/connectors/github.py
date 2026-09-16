"""GitHub connector — ingests issues/PRs assigned to or opened by you.

Single-token auth: a GitHub personal access token (classic or fine-grained,
`repo` read scope). Declared as a `secret_field`, so the UI renders an in-app
field — no .env editing.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..config import get_settings
from .base import Connector, SyncResult

API = "https://api.github.com"


class GitHubConnector(Connector):
    name = "github"
    label = "GitHub"
    # Was never in the scheduler's list, for no reason anyone recorded: a
    # token-backed source the user connected that then never refreshed.
    auto_sync = True
    incremental = True
    secret_field = {
        "key": "GITHUB_TOKEN",
        "label": "GitHub personal access token",
        "placeholder": "ghp_… / github_pat_…",
        "help_url": "https://github.com/settings/tokens",
        "steps": [
            "Open <b>github.com/settings/tokens</b> → <b>Generate new token</b> "
            "with <b>repo</b> (read) scope, then copy it.",
            "Paste it below and click Save.",
        ],
    }

    def is_configured(self) -> tuple[bool, str]:
        if get_settings().get_secret("GITHUB_TOKEN"):
            return True, ""
        return False, "click setup to paste your GitHub token"

    def _get(self, path: str, token: str) -> Any:
        req = urllib.request.Request(
            f"{API}{path}",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "Chitragupta"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def sync(self, *, max_items: int = 150, since: str | None = None,
             limit: int | None = None, full_history: bool = False,
             cancel=None, progress=None, **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        token = get_settings().get_secret("GITHUB_TOKEN")
        if not token:
            result.errors.append("GitHub token not set")
            return self._finish(result)
        started = self.now()
        resume = since if since is not None else self.since(full_history=full_history)
        max_items = limit or max_items
        try:
            # issues + PRs involving the authenticated user, most-recent first
            params = {"filter": "involves", "state": "all", "sort": "updated",
                      "per_page": min(max_items, 100)}
            if resume:
                # GitHub's own "updated since" filter, so an unchanged backlog
                # is not re-downloaded on every background pass.
                params["since"] = resume
            q = urllib.parse.urlencode(params)
            items = self._get(f"/issues?{q}", token)
            from ..brain import get_brain
            brain = get_brain()

            def ingest(it) -> int:
                is_pr = "pull_request" in it
                repo = (it.get("repository", {}) or {}).get("full_name") or \
                    it.get("html_url", "").split("/issues")[0].split("/pull")[0]
                title = f"{repo}#{it.get('number', '?')}: {it.get('title', '(untitled)')}"
                text = (
                    f"GitHub {'PR' if is_pr else 'issue'} {title}\n"
                    f"State: {it.get('state', '?')}"
                    f" · Author: {(it.get('user') or {}).get('login', '?')}"
                    + (f"\n\n{it['body']}" if it.get("body") else "")
                )
                out = brain.ingest(text, source=self.name,
                                   kind="pr" if is_pr else "issue",
                                   title=title, fast=True, uri=it.get("html_url"))
                return out["memories"]

            self.each_guarded(items[:max_items], result, ingest,
                              cancel=cancel, progress=progress)
            result.detail = result.detail or f"{len(items)} issues/PRs"
            result.cursor = started
        except urllib.error.HTTPError as exc:
            result.errors.append(
                "invalid GitHub token" if exc.code in (401, 403)
                else f"GitHub API error {exc.code}")
            result.detail = "sync failed"
        except Exception as exc:
            result.errors.append(str(exc))
            result.detail = "sync failed"
        return self._finish(result)
