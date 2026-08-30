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


def _looks_html(t: str) -> bool:
    return bool(re.search(r"<[a-z/][^>]*>", t) or
                re.search(r"\{[^{}]*(margin|padding|font|px|color)[^{}]*\}", t))


def _extract_body(payload: dict) -> str:
    """Best readable body: prefer text/plain, else strip text/html."""
    plain, html = _walk_body(payload)
    body = plain.strip() or html_to_text(html)
    # safety net: some senders stuff HTML/CSS into the "plain" part
    if _looks_html(body):
        body = html_to_text(body)
    return body


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

    def sync(self, *, query: str | None = None, max_results: int | None = None,
             full_history: bool = False, interactive: bool = True,
             **_: Any) -> SyncResult:
        """Bounded by default: sync recent mail (fast, lean). Pass
        full_history=True to pull the whole archive (the escape hatch)."""
        result = SyncResult(connector=self.name)
        service = self._service(result, interactive)
        if service is None:
            return self._finish(result)

        from ..config import get_settings
        s = get_settings()
        if query is None:
            query = ("-in:spam -in:trash" if full_history
                     else f"newer_than:{s.gmail_recent_days}d -in:spam -in:trash")
        max_results = max_results or (s.gmail_max if full_history else s.gmail_recent_max)
        try:
            messages = self._list(service, query, max_results)
            for meta in messages:
                if self._ingest_message(service, meta):
                    result.added += 1
                else:
                    result.skipped += 1
            scope = "all mail" if full_history else f"last {s.gmail_recent_days}d"
            result.detail = f"{scope}, {len(messages)} messages"
        except Exception as exc:
            result.errors.append(str(exc))
            result.detail = "sync failed"
        return self._finish(result)

    def search_and_ingest(self, terms: str, max_results: int = 8,
                          interactive: bool = False) -> list[str]:
        """On-demand: live Gmail search (full-text + operators) that ingests
        matching messages so a specific/older email is fetched only when asked."""
        terms = (terms or "").strip()
        if not terms:
            return []
        service = self._service(None, interactive)
        if service is None:
            return []
        try:
            q = f"({terms}) -in:spam -in:trash"
            messages = self._list(service, q, max_results)
            found = []
            for meta in messages:
                title = self._ingest_message(service, meta, return_title=True)
                if title:
                    found.append(title)
            return found
        except Exception:
            return []

    # ── helpers ──────────────────────────────────────────────────────────
    def send_email(self, to: str, subject: str, body: str,
                   interactive: bool = False) -> dict:
        """Send an email (WRITE). Only ever called after user confirmation."""
        service = self._service(None, interactive)
        if service is None:
            return {"ok": False, "error": "Gmail not connected"}
        try:
            import base64
            from email.mime.text import MIMEText
            msg = MIMEText(body)
            msg["to"] = to
            msg["subject"] = subject
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            sent = service.users().messages().send(
                userId="me", body={"raw": raw}).execute()
            return {"ok": True, "id": sent.get("id"),
                    "detail": f"Email sent to {to}"}
        except Exception as exc:
            m = str(exc)
            if "insufficient" in m.lower() or "scope" in m.lower() or "403" in m:
                return {"ok": False, "error": "Gmail needs re-authorization to "
                        "SEND. Reconnect Google (Connectors → Gmail → Reconnect) "
                        "and approve the send permission, then try again.",
                        "reauth": True}
            return {"ok": False, "error": m[:200]}

    def _service(self, result, interactive):
        try:
            from googleapiclient.discovery import build  # lazy
        except ImportError:
            if result is not None:
                result.errors.append("pip install .[gmail] to use Gmail")
            return None
        try:
            creds = get_credentials(interactive=interactive)
            return build("gmail", "v1", credentials=creds, cache_discovery=False)
        except Exception as exc:
            if result is not None:
                result.errors.append(str(exc))
            return None

    def _list(self, service, query, max_results) -> list[dict]:
        messages: list[dict] = []
        page_token = None
        while len(messages) < max_results:
            resp = (service.users().messages()
                    .list(userId="me", q=query, pageToken=page_token,
                          maxResults=min(500, max_results - len(messages))).execute())
            messages += resp.get("messages", [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return messages

    def _ingest_message(self, service, meta, return_title=False):
        msg = (service.users().messages()
               .get(userId="me", id=meta["id"], format="full").execute())
        headers = {h["name"].lower(): h["value"]
                   for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("subject", "(no subject)")
        sender = headers.get("from", "")
        body = _extract_body(msg.get("payload", {})).strip()
        snippet = body or msg.get("snippet", "")
        if not snippet:
            return None if return_title else False
        text = f"From: {sender}\nSubject: {subject}\n\n{snippet[:4000]}"
        event_date = None
        if msg.get("internalDate"):
            from datetime import datetime, timezone
            event_date = datetime.fromtimestamp(
                int(msg["internalDate"]) / 1000, timezone.utc).date().isoformat()
        mem = self.store.add(
            text=text, source=self.name, kind="email", title=subject,
            uri=f"https://mail.google.com/mail/#all/{meta['id']}",
            event_date=event_date,
            metadata={"from": sender, "message_id": meta["id"], "date": event_date})
        if return_title:
            return subject
        return bool(mem)
