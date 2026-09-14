"""Action framework — agents propose, the user confirms, Lodestone executes.

Nothing here runs without an explicit user confirmation (the API endpoint is
only called from a UI Confirm button). Each action validates its params and
runs the corresponding connector's WRITE method.
"""
from __future__ import annotations

import re
from typing import Any

from .connectors import get_connector

_ACTION_RE = re.compile(r"<action\s+([^>]*?)>(.*?)</action>", re.I | re.S)
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_actions(text: str) -> list[dict]:
    """Extract <action …>…</action> proposals from a model reply (server-side
    twin of the UI parser) so routines can auto-execute them."""
    out = []
    for attrs, inner in _ACTION_RE.findall(text or ""):
        a: dict = {"params": {}}
        for k, v in _ATTR_RE.findall(attrs):
            if k == "type":
                a["type"] = v
            else:
                a["params"][k] = v
        t = a.get("type")
        if t == "send_email":
            a["params"]["body"] = inner.strip()
        elif t == "create_event":
            a["params"]["description"] = inner.strip()
        elif t == "set_reminder":
            a["params"]["message"] = inner.strip()
        elif t == "create_routine":
            a["params"]["instruction"] = inner.strip()
        elif t == "mcp_action":
            # A vendor's tool takes an object, and an action tag's attributes
            # are flat strings — so the arguments are the body, as JSON.
            a["params"]["server_id"] = (a["params"].pop("server", "")
                                        or a["params"].get("server_id", ""))
            parsed = _arguments(inner)
            if parsed is None:
                # Malformed JSON is dropped, never guessed at. Half-parsing a
                # model's arguments and running the result is how an action
                # does something nobody proposed.
                continue
            a["params"]["arguments"] = parsed
        if t:
            out.append(a)
    return out


def _arguments(inner: str) -> dict | None:
    """The JSON object inside an `mcp_action` tag, or None if it is not one.

    Tolerates a fenced block, because models wrap JSON in ``` roughly half the
    time and a refused action teaches the user nothing about why.
    """
    import json

    text = (inner or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    text = text.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _send_email(params: dict) -> dict:
    to = (params.get("to") or "").strip()
    subject = (params.get("subject") or "").strip()
    body = params.get("body") or ""
    if not _EMAIL_RE.match(to):
        return {"ok": False,
                "error": f"'{to}' is not a valid email address" if to
                else "a recipient (to) is required"}
    gmail = _writer("gmail", "send_email")
    if gmail is None:
        return {"ok": False, "error": "Gmail is not connected for sending mail."}
    return gmail.send_email(to, subject, body)


def _writer(source: str, capability: str):
    """The connector for `source`, only if it can actually perform `capability`.

    Connectors are duck-typed: `send_email` and `create_event` live on the Gmail
    and Calendar classes, not on the base `Connector`. If a source is connected
    read-only — or a future connector simply does not implement the write — the
    bare call raises AttributeError, and the user is shown a 500 with a Python
    traceback in it. Returning None instead lets the caller say what happened.
    """
    connector = get_connector(source)
    return connector if callable(getattr(connector, capability, None)) else None


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


def _create_routine(params: dict) -> dict:
    from .routines import get_routines
    instruction = (params.get("instruction") or params.get("body") or "").strip()
    if not instruction:
        return {"ok": False, "error": "an instruction is required"}
    name = (params.get("name") or "Automation").strip()
    trigger = params.get("trigger") or "new_email"
    if trigger not in ("new_email", "schedule"):
        trigger = "new_email"
    agent = params.get("agent") or params.get("agent_id") or "personal"
    interval = int(params.get("interval_min") or 60)
    get_routines().create(name, agent, trigger, instruction, interval)
    when = "on every new email" if trigger == "new_email" else f"every {interval} min"
    return {"ok": True, "detail": f"Automation '{name}' created — runs {when}"}


def _create_event(params: dict) -> dict:
    title = (params.get("title") or "").strip()
    start = (params.get("start") or "").strip()
    if not title or not start:
        return {"ok": False, "error": "title and start (ISO datetime) required"}
    attendees = params.get("attendees")
    if isinstance(attendees, str):
        attendees = [a.strip() for a in attendees.split(",") if a.strip()]
    gcal = _writer("gcal", "create_event")
    if gcal is None:
        return {"ok": False, "error": "Google Calendar is not connected for creating events."}
    return gcal.create_event(
        title, start, params.get("end"), params.get("description", ""), attendees)


def _mcp_action(params: dict) -> dict:
    """Run one tool on a connector the user added.

    Registered here rather than executed inside the connector so it travels the
    same road as sending an email: proposed, queued if nobody is watching,
    approved from the same list, recorded with the same history. The connector
    had its own private confirmation flag, which was a second answer to a
    question this file already answers.
    """
    from .connectors import get_connector
    from .connectors.mcp_source import MCPConnector

    server_id = (params.get("server_id") or "").strip()
    tool = (params.get("tool") or "").strip()
    if not server_id or not tool:
        return {"ok": False, "error": "That action is missing its connector."}
    try:
        conn = get_connector(f"mcp:{server_id}")
    except KeyError:
        return {"ok": False, "error": "That connector is no longer set up."}
    if not isinstance(conn, MCPConnector):       # pragma: no cover - unreachable
        # The concrete type, not the base: this is the one handler that mutates
        # somebody else's account, and a duck-typed lookup would happily call
        # `perform` on anything that later grew the name.
        return {"ok": False, "error": "That connector cannot run actions."}
    # `confirmed=True` because reaching this handler *is* the confirmation:
    # nothing calls it except an approval the user granted or a live click.
    return conn.perform(tool, params.get("arguments") or {}, confirmed=True)


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
    "create_routine": {
        "handler": _create_routine, "label": "Create automation",
        "fields": ["name", "trigger", "agent", "interval_min", "instruction"],
    },
    "mcp_action": {
        "handler": _mcp_action, "label": "Connector action",
        "fields": ["server_id", "tool", "arguments"],
    },
}


def run_now(action_type: str, params: dict) -> dict:
    """Run an action immediately (used by the scheduler for due scheduled ones)."""
    spec = REGISTRY.get(action_type)
    if not spec:
        return {"ok": False, "error": f"unknown action '{action_type}'"}
    try:
        return spec["handler"](params or {})
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def execute(action_type: str, params: dict) -> dict:
    """Confirm-time execution. If the action carries an `at` time (and supports
    scheduling), SCHEDULE it to fire later instead of running now — the user has
    confirmed both the content and the time."""
    spec = REGISTRY.get(action_type)
    if not spec:
        return {"ok": False, "error": f"unknown action '{action_type}'"}
    params = params or {}

    at = (params.get("at") or "").strip()
    if at and action_type in ("send_email", "create_event"):
        from datetime import datetime

        from .reminders import parse_when
        from .scheduled import get_scheduled
        fire_at = parse_when(at)
        if not fire_at:
            return {"ok": False, "error": f"couldn't understand the time '{at}'"}
        sched_params = {k: v for k, v in params.items() if k != "at"}
        get_scheduled().add(action_type, sched_params, fire_at,
                            params.get("agent_id"))
        nice = datetime.fromisoformat(fire_at).strftime("%a %b %d, %-I:%M %p")
        verb = "Email" if action_type == "send_email" else "Event"
        return {"ok": True, "scheduled": True,
                "detail": f"{verb} scheduled — will fire automatically at {nice}"}

    return run_now(action_type, params)
