"""Apple Mail connector — reads mail straight off disk, NO OAuth.

macOS Mail stores every message locally as .emlx files under ~/Library/Mail.
If a user has their Gmail (or any account) in Apple Mail, their mail is already
on the machine — Lodestone can read it with zero Google auth (just Full Disk
Access, like iMessage).
"""
from __future__ import annotations

import email
import os
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .base import Connector, SyncResult
from .gmail import html_to_text

MAIL_ROOT = Path.home() / "Library" / "Mail"


def _mail_dirs() -> list[Path]:
    # Mail versions its store: V2 … V10
    return sorted(MAIL_ROOT.glob("V*"), reverse=True) if MAIL_ROOT.exists() else []


def parse_emlx(path: Path) -> dict | None:
    """.emlx = <byte-length>\\n<RFC822 message><plist trailer>."""
    try:
        data = path.read_bytes()
    except Exception:
        return None
    nl = data.find(b"\n")
    length = None
    if nl != -1:
        try:
            length = int(data[:nl].strip())
        except ValueError:
            length = None
    raw = data[nl + 1: nl + 1 + length] if length else data
    msg = email.message_from_bytes(raw)

    subject = msg.get("subject", "(no subject)")
    sender = msg.get("from", "")
    date_iso = None
    if msg.get("date"):
        try:
            date_iso = parsedate_to_datetime(msg["date"]).date().isoformat()
        except Exception:
            date_iso = None

    body = ""
    if msg.is_multipart():
        plain = html = ""
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and not plain:
                plain = part.get_payload(decode=True) or b""
                plain = plain.decode(part.get_content_charset() or "utf-8", "ignore")
            elif ctype == "text/html" and not html:
                html = part.get_payload(decode=True) or b""
                html = html.decode(part.get_content_charset() or "utf-8", "ignore")
        body = plain.strip() or html_to_text(html)
    else:
        payload = msg.get_payload(decode=True) or b""
        text = payload.decode(msg.get_content_charset() or "utf-8", "ignore")
        body = html_to_text(text) if msg.get_content_type() == "text/html" else text
    return {"subject": subject, "sender": sender, "date": date_iso,
            "body": body.strip()}


class AppleMailConnector(Connector):
    name = "apple_mail"
    label = "Apple Mail"

    def is_configured(self) -> tuple[bool, str]:
        dirs = _mail_dirs()
        if not dirs:
            return False, "no Apple Mail data (add an account in the Mail app)"
        try:
            next(dirs[0].rglob("*.emlx"), None)
            return True, ""
        except PermissionError:
            return False, ("grant Full Disk Access to Lodestone/your terminal "
                           "(System Settings → Privacy & Security → Full Disk Access)")

    def sync(self, *, max_messages: int = 800, **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        ready, reason = self.is_configured()
        if not ready:
            result.errors.append(reason)
            return self._finish(result)
        try:
            files: list[Path] = []
            for root in _mail_dirs():
                for dp, dn, fn in os.walk(root):
                    if "/Trash.mbox/" in dp or "/Junk.mbox/" in dp:
                        continue
                    files += [Path(dp) / f for f in fn if f.endswith(".emlx")]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for fp in files[:max_messages]:
                m = parse_emlx(fp)
                if not m or not (m["body"] or m["subject"]):
                    result.skipped += 1
                    continue
                text = (f"From: {m['sender']}\nSubject: {m['subject']}\n\n"
                        f"{(m['body'] or '')[:4000]}")
                mem = self.store.add(
                    text=text, source=self.name, kind="email",
                    title=m["subject"], event_date=m["date"],
                    metadata={"from": m["sender"], "date": m["date"]})
                result.added += 1 if mem else 0
                result.skipped += 0 if mem else 1
            result.detail = f"scanned {len(files)} local messages"
        except Exception as exc:
            result.errors.append(str(exc))
            result.detail = "sync failed"
        return self._finish(result)
