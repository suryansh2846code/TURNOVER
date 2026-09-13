"""The workspace around the agents: actions, routines, reminders, tasks, and the pages themselves."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...log import get_logger
from ..assets import WEB

log = get_logger(__name__)
router = APIRouter()


@router.post("/api/open-browser")
def open_browser_endpoint(payload: dict):
    import webbrowser

    from ..security import is_safe_external_url

    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(400, "url is required")
    # Only ever a web page. Without this the endpoint hands any installed app's
    # custom scheme — or a local file — to the system opener.
    if not is_safe_external_url(url):
        raise HTTPException(400, "Only http:// and https:// links can be opened.")
    try:
        webbrowser.open(url)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, f"Failed to open browser: {exc}") from exc


@router.get("/signin-hud")
def signin_hud_page():
    """The floating sign-in card (desktop app only)."""
    return FileResponse(WEB / "signin_hud.html")


class HudNoteIn(BaseModel):
    """What the page decided to do with a sign-in click."""
    provider: str = ""
    branch: str = ""
    detail: str = ""


@router.post("/api/hud/note")
def hud_note(body: HudNoteIn):
    """The page reports which sign-in branch it took.

    Only the frontend knows whether the floating card was skipped because the
    provider was already connected, or asked for and refused. Without that, the
    two are indistinguishable from the backend.
    """
    from ... import hud

    hud.note("branch", provider=body.provider, branch=body.branch,
             detail=body.detail[:200])
    return {"ok": True}


@router.get("/api/hud/diagnostics")
def hud_diagnostics():
    """Whether the floating sign-in window exists, and what the last click did."""
    from ... import hud
    from ...models import login_processes

    return {**hud.diagnostics(), "login_processes": login_processes.alive()}


# ── actions (execute only after explicit user confirmation) ───────────────
class ActionIn(BaseModel):
    type: str
    params: dict[str, Any] = {}


@router.post("/api/actions/execute")
def execute_action(body: ActionIn):
    from ...actions import execute
    return execute(body.type, body.params)


class NewRoutine(BaseModel):
    name: str
    agent_id: str = "personal"
    trigger: str = "new_email"          # new_email | schedule
    instruction: str
    interval_min: int = 60


@router.get("/api/routines")
def list_routines():
    from ...routines import get_routines
    return {"routines": get_routines().list()}


@router.post("/api/routines")
def create_routine(body: NewRoutine):
    from ...routines import get_routines
    return get_routines().create(body.name, body.agent_id, body.trigger,
                                 body.instruction, body.interval_min)


@router.post("/api/routines/{rid}/toggle")
def toggle_routine(rid: str, on: bool = True):
    from ...routines import get_routines
    get_routines().toggle(rid, on)
    return {"ok": True}


@router.delete("/api/routines/{rid}")
def delete_routine(rid: str):
    from ...routines import get_routines
    return {"deleted": get_routines().delete(rid)}


@router.get("/api/reminders")
def list_reminders():
    import json as _json

    from ...reminders import get_reminders
    from ...scheduled import get_scheduled
    items = [{"kind": "reminder", "id": r["id"], "label": r["message"],
              "fire_at": r["fire_at"], "agent_id": r.get("agent_id")}
             for r in get_reminders().upcoming()]
    for a in get_scheduled().upcoming():
        p = _json.loads(a["params"] or "{}")
        label = (f"Send email to {p.get('to', '')}" if a["type"] == "send_email"
                 else f"Create event: {p.get('title', '')}")
        items.append({"kind": "action", "id": a["id"], "label": "⏳ " + label,
                      "fire_at": a["fire_at"], "agent_id": a.get("agent_id")})
    items.sort(key=lambda x: x["fire_at"])
    return {"reminders": items}


@router.delete("/api/reminders/{rid}")
def delete_reminder(rid: str):
    from ...reminders import get_reminders
    from ...scheduled import get_scheduled
    ok = get_reminders().delete(rid) or get_scheduled().delete(rid)
    return {"deleted": ok}


# ── tasks ─────────────────────────────────────────────────────────────────
class TaskIn(BaseModel):
    title: str
    due: str | None = None


@router.get("/api/tasks")
def list_tasks(when: str | None = None, include_done: bool = False):
    from ...tasks import get_tasks
    ts = get_tasks()
    return {"tasks": ts.list(when=when, include_done=include_done),
            "stats": ts.stats()}


@router.post("/api/tasks")
def add_task(body: TaskIn):
    from ...tasks import get_tasks
    return get_tasks().add(body.title, body.due)


@router.post("/api/tasks/{tid}/complete")
def complete_task(tid: str):
    from ...tasks import get_tasks
    t = get_tasks().complete(tid)
    if not t:
        raise HTTPException(404, "no task matched")
    return t


@router.delete("/api/tasks/{tid}")
def delete_task(tid: str):
    from ...tasks import get_tasks
    if not get_tasks().delete(tid):
        raise HTTPException(404, "no task matched")
    return {"deleted": tid}


# ── local filesystem browser (for the folder picker) ─────────────────────
@router.get("/api/fs/browse")
def fs_browse(path: str | None = None):
    """List subdirectories of a path so the UI can offer a native-feeling
    folder picker for the files connector. Read-only, dirs only."""
    base = Path(path).expanduser() if path else Path.home()
    try:
        base = base.resolve()
    except Exception:
        base = Path.home()
    if not base.exists() or not base.is_dir():
        base = Path.home()

    dirs, ingestible = [], 0
    try:
        for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith(".") or entry.name in {
                "node_modules", "__pycache__", ".venv", "venv"}:
                continue
            if entry.is_dir():
                dirs.append(entry.name)
            elif entry.suffix.lower() in {
                ".md", ".txt", ".py", ".js", ".ts", ".tsx", ".json",
                ".yaml", ".yml", ".html", ".css", ".rst"}:
                ingestible += 1
    except PermissionError:
        pass
    return {
        "path": str(base),
        "parent": str(base.parent) if base.parent != base else None,
        "home": str(Path.home()),
        "dirs": dirs,
        "ingestible_here": ingestible,
    }


# ── dashboard ─────────────────────────────────────────────────────────────
@router.get("/")
def index():
    return FileResponse(WEB / "index.html")


@router.get("/onboarding")
def onboarding():
    return FileResponse(WEB / "onboarding.html")
