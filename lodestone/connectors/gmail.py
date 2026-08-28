"""Gmail connector — ingests recent email context (read-only)."""
from __future__ import annotations

import base64
from typing import Any

from .base import Connector, SyncResult
from .google_auth import get_credentials, google_ready


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="ignore")


def _extract_body(payload: dict) -> str:
    """Walk the MIME tree for the first text/plain part."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        body = _extract_body(part)
        if body:
            return body
    if payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    return ""


class GmailConnector(Connector):
    name = "gmail"
    label = "Gmail"

    def is_configured(self) -> tuple[bool, str]:
        return google_ready()

    def sync(self, *, query: str = "newer_than:30d -in:spam -in:trash",
             max_results: int = 50, interactive: bool = True, **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        try:
            from googleapiclient.discovery import build  # lazy
        except ImportError:
            result.errors.append("pip install .[gmail] to use the Gmail connector")
            return self._finish(result)

        try:
            creds = get_credentials(interactive=interactive)
            service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            listing = (
                service.users().messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            messages = listing.get("messages", [])
            for meta in messages:
                msg = (
                    service.users().messages()
                    .get(userId="me", id=meta["id"], format="full")
                    .execute()
                )
                headers = {
                    h["name"].lower(): h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                subject = headers.get("subject", "(no subject)")
                sender = headers.get("from", "")
                body = _extract_body(msg.get("payload", {})).strip()
                snippet = body or msg.get("snippet", "")
                if not snippet:
                    result.skipped += 1
                    continue
                text = f"From: {sender}\nSubject: {subject}\n\n{snippet[:4000]}"
                mem = self.store.add(
                    text=text,
                    source=self.name,
                    kind="email",
                    title=subject,
                    uri=f"https://mail.google.com/mail/#all/{meta['id']}",
                    metadata={"from": sender, "message_id": meta["id"]},
                )
                if mem:
                    result.added += 1
                else:
                    result.skipped += 1
            result.detail = f"query '{query}', {len(messages)} messages"
        except Exception as exc:
            result.errors.append(str(exc))
            result.detail = "sync failed"
        return self._finish(result)
