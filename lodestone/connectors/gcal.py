"""Google Calendar connector — ingests recent + upcoming events (read-only)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .base import Connector, SyncResult
from .google_auth import get_credentials, google_ready


class GoogleCalendarConnector(Connector):
    name = "gcal"
    label = "Google Calendar"

    def is_configured(self) -> tuple[bool, str]:
        return google_ready()

    def sync(self, *, days_back: int = 14, days_ahead: int = 30,
             max_results: int = 100, interactive: bool = True, **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        try:
            from googleapiclient.discovery import build  # lazy
        except ImportError:
            result.errors.append("pip install .[gdrive] to use the Calendar connector")
            return self._finish(result)

        try:
            creds = get_credentials(interactive=interactive)
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            now = datetime.now(timezone.utc)
            time_min = (now - timedelta(days=days_back)).isoformat()
            time_max = (now + timedelta(days=days_ahead)).isoformat()
            events = (
                service.events().list(
                    calendarId="primary", timeMin=time_min, timeMax=time_max,
                    maxResults=max_results, singleEvents=True, orderBy="startTime",
                ).execute()
            ).get("items", [])
            from ..brain import get_brain
            brain = get_brain()
            for ev in events:
                summary = ev.get("summary", "(no title)")
                start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
                end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date", "")
                where = ev.get("location", "")
                attendees = ", ".join(
                    a.get("email", "") for a in ev.get("attendees", []) or [])
                desc = (ev.get("description", "") or "")[:1000]
                text = (f"Event: {summary}\nWhen: {start} → {end}"
                        + (f"\nWhere: {where}" if where else "")
                        + (f"\nWith: {attendees}" if attendees else "")
                        + (f"\n\n{desc}" if desc else ""))
                out = brain.ingest(
                    text, source=self.name, kind="event", title=summary,
                    uri=ev.get("htmlLink"), fast=True,
                    metadata={"start": start, "event_id": ev.get("id")},
                )
                result.added += out["memories"]
                if not out["memories"]:
                    result.skipped += 1
            result.detail = f"{len(events)} events ({days_back}d back, {days_ahead}d ahead)"
        except Exception as exc:
            result.errors.append(str(exc))
            result.detail = "sync failed"
        return self._finish(result)
