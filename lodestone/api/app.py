"""FastAPI: the workspace control plane + chat + dashboard."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agents import list_agents, run_turn
from ..agents.agent import AgentMemory
from ..brain import get_brain
from ..config import get_settings
from ..connectors import REGISTRY, get_connector
from ..models import list_providers

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Lodestone", version="0.2.0")


class ChatIn(BaseModel):
    message: str
    provider: str | None = None


class IngestIn(BaseModel):
    text: str
    title: str | None = None
    source: str = "notes"


class SyncIn(BaseModel):
    params: dict[str, Any] = {}


# ── agents & chat ─────────────────────────────────────────────────────────
@app.get("/api/agents")
def agents():
    mem = AgentMemory()
    return {"agents": [
        {"id": a.id, "name": a.name, "role": a.role, "tools": a.tools,
         "messages": len(mem.history(a.id, limit=1000))}
        for a in list_agents()
    ]}

@app.get("/api/agents/{agent_id}/history")
def history(agent_id: str):
    return {"history": AgentMemory().history(agent_id, limit=100)}

@app.post("/api/agents/{agent_id}/chat")
def chat(agent_id: str, body: ChatIn):
    try:
        result = run_turn(agent_id, body.message, provider_name=body.provider)
    except KeyError:
        raise HTTPException(404, f"unknown agent '{agent_id}'")
    except Exception as exc:  # never 500 the chat — return a readable message
        return {"agent_id": agent_id, "provider": "", "model": "", "trace": [],
                "reply": f"⚠️ Something went wrong: {str(exc)[:200]}"}
    return result.as_dict()

@app.post("/api/agents/{agent_id}/clear")
def clear(agent_id: str):
    AgentMemory().clear(agent_id)
    return {"cleared": agent_id}


# ── brain ─────────────────────────────────────────────────────────────────
@app.get("/api/brain/stats")
def brain_stats():
    return get_brain().stats()

@app.get("/api/brain/entities")
def entities(limit: int = 30):
    return {"entities": get_brain().graph.top_entities(limit=limit)}

@app.post("/api/brain/ingest")
def ingest(body: IngestIn):
    out = get_brain().ingest(body.text, source=body.source, title=body.title)
    return out

@app.post("/api/brain/recall")
def recall(body: ChatIn):
    return get_brain().recall(body.message)


# ── models & connectors ───────────────────────────────────────────────────
@app.get("/api/providers")
def providers():
    s = get_settings()
    return {"active": s.model_provider, "providers": list_providers()}

@app.get("/api/connectors")
def connectors():
    brain = get_brain()
    state = brain.store.all_connector_state()
    out = []
    for name, cls in REGISTRY.items():
        inst = cls()
        ready, reason = inst.is_configured()
        out.append({"name": name, "label": cls.label, "ready": ready,
                    "reason": reason, "always_available": cls.always_available,
                    "state": state.get(name)})
    return {"connectors": out}

@app.post("/api/connectors/{name}/sync")
def sync(name: str, body: SyncIn):
    try:
        conn = get_connector(name)
    except KeyError:
        raise HTTPException(404, f"unknown connector '{name}'")
    # route ingestion through the brain so the graph is built too
    res = conn.sync(**body.params)
    return res.as_dict()


# ── tasks ─────────────────────────────────────────────────────────────────
class TaskIn(BaseModel):
    title: str
    due: str | None = None

@app.get("/api/tasks")
def list_tasks(when: str | None = None, include_done: bool = False):
    from ..tasks import get_tasks
    ts = get_tasks()
    return {"tasks": ts.list(when=when, include_done=include_done),
            "stats": ts.stats()}

@app.post("/api/tasks")
def add_task(body: TaskIn):
    from ..tasks import get_tasks
    return get_tasks().add(body.title, body.due)

@app.post("/api/tasks/{tid}/complete")
def complete_task(tid: str):
    from ..tasks import get_tasks
    t = get_tasks().complete(tid)
    if not t:
        raise HTTPException(404, "no task matched")
    return t

@app.delete("/api/tasks/{tid}")
def delete_task(tid: str):
    from ..tasks import get_tasks
    if not get_tasks().delete(tid):
        raise HTTPException(404, "no task matched")
    return {"deleted": tid}


# ── local filesystem browser (for the folder picker) ─────────────────────
@app.get("/api/fs/browse")
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
@app.get("/")
def index():
    return FileResponse(WEB / "index.html")

app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


def run() -> None:
    import uvicorn
    s = get_settings()
    print(f"\n  ◆ Lodestone workspace → http://{s.host}:{s.port}")
    print(f"    model: {s.model_provider}   brain: {s.home}\n")
    uvicorn.run(app, host=s.host, port=s.port, log_level="info")
