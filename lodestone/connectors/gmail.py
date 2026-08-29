"""Gmail connector — ingests recent email context (read-only)."""
from __future__ import annotations

import base64
import re
from typing import Any

from .base import Connector, SyncResult
from .google_auth import get_credentials, google_ready


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="ignore")


def html_to_text(html: str) -> str:
    """Strip HTML/CSS/scripts from an email body → readable plain text."""
    html = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)                 # remaining tags
    # decode a few common entities
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'"), ("&zwnj;", "")):
        html = html.replace(a, b)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n\s*\n\s*\n+", "\n\n", html)
    return html.strip()


def _extract_body(payload: dict) -> str:
    """Best readable body: prefer text/plain, else strip text/html."""
    plain, html = _walk_body(payload)
    if plain.strip():
        return plain
    if html.strip():
        return html_to_text(html)
    return ""


def _walk_body(payload: dict) -> tuple[str, str]:
    """Return (text/plain, text/html) found anywhere in the MIME tree."""
    plain, html = "", ""
    mime = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if data:
        if mime == "text/plain":
            plain += _decode(data)
        elif mime == "text/html":
            html += _decode(data)
    for part in payload.get("parts", []) or []:
        p, h = _walk_body(part)
        plain += p
        html += h
    return plain, html


class GmailConnector(Connector):
    name = "gmail"
    label = "Gmail"

    def is_configured(self) -> tuple[bool, str]:
        return google_ready()

    def sync(self, *, query: str = "-in:spam -in:trash",
             max_results: int | None = None, interactive: bool = True,
             **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        try:
            from googleapiclient.discovery import build  # lazy
        except ImportError:
            result.errors.append("pip install .[gmail] to use the Gmail connector")
            return self._finish(result)

        from ..config import get_settings
        max_results = max_results or get_settings().gmail_max
        try:
            creds = get_credentials(interactive=interactive)
            service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            # paginate to gather up to max_results across pages
            messages: list[dict] = []
            page_token = None
            while len(messages) < max_results:
                resp = (
                    service.users().messages()
                    .list(userId="me", q=query, pageToken=page_token,
                          maxResults=min(500, max_results - len(messages)))
                    .execute()
                )
                messages += resp.get("messages", [])
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
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
                event_date = None
                if msg.get("internalDate"):
                    from datetime import datetime, timezone
                    event_date = datetime.fromtimestamp(
                        int(msg["internalDate"]) / 1000, timezone.utc
                    ).date().isoformat()
                mem = self.store.add(
                    text=text,
                    source=self.name,
                    kind="email",
                    title=subject,
                    uri=f"https://mail.google.com/mail/#all/{meta['id']}",
                    event_date=event_date,
                    metadata={"from": sender, "message_id": meta["id"],
                              "date": event_date},
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
