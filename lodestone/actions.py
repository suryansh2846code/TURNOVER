"""Action framework — agents propose, the user confirms, Lodestone executes.

Nothing here runs without an explicit user confirmation (the API endpoint is
only called from a UI Confirm button). Each action validates its params and
runs the corresponding connector's WRITE method.
"""
from __future__ import annotations

from typing import Any, Callable

from .connectors import get_connector


def _send_email(params: dict) -> dict:
    to = (params.get("to") or "").strip()
    subject = (params.get("subject") or "").strip()
    body = params.get("body") or ""
    if not to or "@" not in to:
        return {"ok": False, "error": "a valid recipient (to) is required"}
    return get_connector("gmail").send_email(to, subject, body)


def _set_reminder(params: dict) -> dict:
    from .reminders import get_reminders, parse_when
    message = (params.get("message") or params.get("body") or "").strip()
    when = params.get("at") or params.get("when") or ""
    if not message:
        return {"ok": False, "error": "reminder message required"}
    fire_at = parse_when(when)
    if not fire_at:
        return {"ok": False, "error": f"couldn't understand the time '{when}'"}
    r = get_reminders().add(message, fire_at, params.get("agent_id"))
    from datetime import datetime
    nice = datetime.fromisoformat(r["fire_at"]).strftime("%a %b %d, %-I:%M %p")
    return {"ok": True, "detail": f"Reminder set for {nice}"}


def _create_event(params: dict) -> dict:
    title = (params.get("title") or "").strip()
    start = (params.get("start") or "").strip()
    if not title or not start:
        return {"ok": False, "error": "title and start (ISO datetime) required"}
    attendees = params.get("attendees")
    if isinstance(attendees, str):
        attendees = [a.strip() for a in attendees.split(",") if a.strip()]
    return get_connector("gcal").create_event(
        title, start, params.get("end"), params.get("description", ""), attendees)


# action name → (handler, human label, required params)
REGISTRY: dict[str, dict[str, Any]] = {
    "send_email": {
        "handler": _send_email, "label": "Send email",
        "fields": ["to", "subject", "body"],
    },
    "create_event": {
        "handler": _create_event, "label": "Create calendar event",
        "fields": ["title", "start", "end", "description", "attendees"],
    },
    "set_reminder": {
        "handler": _set_reminder, "label": "Set reminder",
        "fields": ["message", "at"],
    },
}


def execute(action_type: str, params: dict) -> dict:
    spec = REGISTRY.get(action_type)
    if not spec:
        return {"ok": False, "error": f"unknown action '{action_type}'"}
    try:
        return spec["handler"](params or {})
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}
