"""Apple Calendar connector — reads events off disk, NO OAuth.

macOS Calendar stores each event as a local .ics file under ~/Library/Calendars.
Read them directly (Full Disk Access) — no Google/iCloud auth needed.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import Connector, SyncResult

CAL_ROOT = Path.home() / "Library" / "Calendars"


def _unfold(text: str) -> str:
    # ICS folds long lines with CRLF + space/tab
    return re.sub(r"\r?\n[ \t]", "", text)


def _fmt_dt(raw: str) -> str:
    # 20260901T150000Z or 20260901 → ISO-ish date
    m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?", raw)
    if not m:
        return raw
    y, mo, d, h, mi = m.groups()
    return f"{y}-{mo}-{d}" + (f"T{h}:{mi}" if h else "")


def parse_ics(text: str) -> dict | None:
    text = _unfold(text)
    fields = {}
    for key in ("SUMMARY", "LOCATION", "DESCRIPTION"):
        m = re.search(rf"^{key}(?:;[^:]*)?:(.*)$", text, re.M)
        if m:
            fields[key] = m.group(1).strip().replace("\\,", ",").replace("\\n", " ")
    ds = re.search(r"^DTSTART(?:;[^:]*)?:(.*)$", text, re.M)
    de = re.search(r"^DTEND(?:;[^:]*)?:(.*)$", text, re.M)
    if not fields.get("SUMMARY"):
        return None
    return {"summary": fields["SUMMARY"],
            "start": _fmt_dt(ds.group(1).strip()) if ds else "",
            "end": _fmt_dt(de.group(1).strip()) if de else "",
            "location": fields.get("LOCATION", ""),
            "description": fields.get("DESCRIPTION", "")}


class AppleCalendarConnector(Connector):
    name = "apple_calendar"
    label = "Apple Calendar"
    platforms = ("darwin",)

    def is_configured(self) -> tuple[bool, str]:
        if not CAL_ROOT.exists():
            return False, "no Apple Calendar data (add a calendar in the Calendar app)"
        try:
            next(CAL_ROOT.rglob("*.ics"), None)
            return True, ""
        except PermissionError:
            return False, ("grant Full Disk Access to Lodestone/your terminal "
                           "(System Settings → Privacy & Security → Full Disk Access)")

    def sync(self, *, max_events: int = 500, **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        ready, reason = self.is_configured()
        if not ready:
            result.errors.append(reason)
            return self._finish(result)
        try:
            from ..brain import get_brain
            brain = get_brain()
            files = list(CAL_ROOT.rglob("*.ics"))
            for fp in files[:max_events]:
                try:
                    ev = parse_ics(fp.read_text(errors="ignore"))
                except Exception:
                    continue
                if not ev:
                    result.skipped += 1
                    continue
                text = (f"Event: {ev['summary']}\nWhen: {ev['start']}"
                        + (f" → {ev['end']}" if ev["end"] else "")
                        + (f"\nWhere: {ev['location']}" if ev["location"] else "")
                        + (f"\n\n{ev['description']}" if ev["description"] else ""))
                out = brain.ingest(text, source=self.name, kind="event",
                                   title=ev["summary"], fast=True,
                                   event_date=(ev["start"][:10] if ev["start"] else None))
                result.added += out["memories"]
                if not out["memories"]:
                    result.skipped += 1
            result.detail = f"scanned {len(files)} local events"
        except Exception as exc:
            result.errors.append(str(exc))
            result.detail = "sync failed"
        return self._finish(result)
