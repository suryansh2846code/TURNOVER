"""FastAPI: the workspace control plane + chat + dashboard."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agents import list_agents, run_turn
from ..agents.agent import AgentMemory
from ..brain import get_brain
from ..config import get_settings
from ..connectors import REGISTRY, get_connector
from ..models import list_providers

from ..scheduler import get_scheduler

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Lodestone", version="0.2.0")


@app.middleware("http")
async def _no_cache_assets(request, call_next):
    """Never cache the UI assets, so a code update is picked up on a normal
    reload — no hard-refresh needed."""
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p == "/onboarding" or p.startswith("/static"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.on_event("startup")
def _start_scheduler():
    get_scheduler().start()


@app.get("/api/sync/status")
def sync_status():
    s = get_scheduler()
    st = get_settings()
    return {"enabled": st.sync_enabled, "interval_minutes": st.sync_interval_minutes,
            "syncing": s.syncing, "last_run": s.last_run, "last_result": s.last_result}


@app.post("/api/sync/cancel")
def sync_cancel():
    """Stop an in-flight sync. Cooperative — the current source finishes but no
    further sources are synced, and `syncing` clears shortly after."""
    return {"cancelled": get_scheduler().cancel_sync()}


@app.post("/api/sync/now")
def sync_now():
    import threading
    s = get_scheduler()
    if s.syncing:
        return {"started": False, "reason": "already syncing"}
    threading.Thread(target=s.sync_all, kwargs={"interactive": False},
                     daemon=True).start()
    return {"started": True}


class ChatIn(BaseModel):
    message: str = Field(max_length=24000)   # guardrail against runaway input
    provider: str | None = None
    model: str | None = None


class IngestIn(BaseModel):
    text: str = Field(max_length=200000)
    title: str | None = None
    source: str = "notes"


class SyncIn(BaseModel):
    params: dict[str, Any] = {}


# ── agents & chat ─────────────────────────────────────────────────────────
@app.get("/api/agents")
def agents():
    from ..agents.presets import PRESETS
    mem = AgentMemory()
    return {"agents": [
        {"id": a.id, "name": a.name, "role": a.role, "tools": a.tools,
         "custom": a.id not in PRESETS,
         "messages": len(mem.history(a.id, limit=1000))}
        for a in list_agents()
    ]}

@app.get("/api/agents/{agent_id}/history")
def history(agent_id: str):
    return {"history": AgentMemory().history(agent_id, limit=100)}


class NewAgent(BaseModel):
    name: str
    role: str = ""
    system_prompt: str = ""
    tools: list[str] = []
    recall_sources: list[str] = []

@app.get("/api/agents/tools")
def available_tools():
    from ..agents.tools import TOOL_DEFS
    return {"tools": [{"name": n, "description": t.description}
                      for n, t in TOOL_DEFS.items()]}

@app.post("/api/agents/custom")
def create_agent(body: NewAgent):
    from ..agents.custom import get_custom_store
    a = get_custom_store().create(body.name, body.role, body.system_prompt,
                                  body.tools, body.recall_sources)
    return {"id": a.id, "name": a.name, "role": a.role}

@app.delete("/api/agents/custom/{agent_id}")
def delete_agent(agent_id: str):
    from ..agents.custom import get_custom_store
    if not get_custom_store().delete(agent_id):
        raise HTTPException(404, "not a custom agent")
    AgentMemory().clear(agent_id)
    return {"deleted": agent_id}

@app.post("/api/agents/{agent_id}/chat")
def chat(agent_id: str, body: ChatIn):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(422, "message is empty")
    try:
        result = run_turn(agent_id, message,
                          provider_name=body.provider, model_name=body.model)
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


class ResetIn(BaseModel):
    memories: bool = True   # wipe all memories + graph + connector state
    secrets: bool = True    # forget saved connector tokens (Notion/GitHub/Linear…)
    google: bool = True     # sign out of Google (so onboarding re-consents)


@app.post("/api/brain/reset")
def brain_reset(body: ResetIn | None = None):
    """Start-from-zero: wipe the brain and, optionally, forget every connector
    credential so the onboarding flow reconnects each source from scratch."""
    body = body or ResetIn()
    out: dict[str, Any] = {}
    if body.memories:
        out.update(get_brain().reset())
    if body.secrets:
        cleared = []
        for name, cls in REGISTRY.items():
            field = getattr(cls, "secret_field", None)
            if field and field.get("key"):
                get_settings().set_secret(field["key"], None)
                cleared.append(name)
        out["secrets_cleared"] = cleared
    if body.google:
        try:
            from ..connectors.google_auth import disconnect
            disconnect()
            out["google_disconnected"] = True
        except Exception as exc:
            out["google_disconnected"] = False
            out["google_error"] = str(exc)[:120]
    return out

def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM reply (which may wrap it in prose
    or ```json fences)."""
    import json as _json
    s = (text or "").strip()
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        s = s[a:b + 1]
    return _json.loads(s)


# maps a memory source to one of the four persona buckets
_PERSONA_CAT = {"gmail": "comm", "apple_mail": "comm", "imessage": "comm", "slack": "comm",
                "gcal": "personal", "apple_calendar": "personal",
                "gdrive": "work", "github": "work", "linear": "work", "notion": "work",
                "files": "learning", "notes": "learning"}


def _base_personas() -> list[dict]:
    brain = get_brain()
    by_source = brain.stats().get("by_source", {})
    counts = {"work": 0, "learning": 0, "comm": 0, "personal": 0}
    for src, c in by_source.items():
        counts[_PERSONA_CAT.get(src, _PERSONA_CAT.get(src.split(":")[0], "work"))] += c
    names = [e["name"] for e in brain.graph.top_entities(limit=24)]
    per = max(1, -(-len(names) // 4))

    def themes(i):
        return names[i * per:i * per + per][:5]
    tpl = [("work", "Work", "What you're building and working on."),
           ("learning", "Learning", "What you're exploring and learning."),
           ("comm", "Communication", "Who you talk to and collaborate with."),
           ("personal", "Personal", "Your life outside work.")]
    return [{"key": k, "title": t, "items": counts[k], "themes": themes(i), "summary": s}
            for i, (k, t, s) in enumerate(tpl)]


@app.post("/api/brain/digest")
def brain_digest(body: ChatIn | None = None):
    """The 'Here's your brain' digest — real, LLM-written second-person personas
    grounded in the user's actual brain. Uses the caller's chosen model (falling
    back to the server default), and to counts + themes when there is no data yet
    or no model is connected."""
    from ..models.registry import get_provider
    from ..models.base import Message
    personas = _base_personas()
    brain = get_brain()
    total = brain.stats().get("total", 0)
    s = get_settings()
    provider = get_provider((body.provider if body else None) or s.model_provider,
                            (body.model if body else None) or s.model_name)
    try:
        ready, _ = provider.is_ready()
    except Exception:
        ready = False
    if total == 0 or not ready:
        return {"personas": personas, "generated": False}
    ctx = brain.recall(
        "the user's work and projects, what they're learning, who they "
        "communicate with, and their personal life", limit=24).get("context", "")
    ent_line = ", ".join(e["name"] for e in brain.graph.top_entities(limit=24))
    prompt = (
        "You are profiling a user from their own data. Using ONLY the CONTEXT and "
        "ENTITIES below, write a concise second-person profile in four areas: Work, "
        "Learning, Communication, Personal. For each area give 2-3 concrete sentences "
        "about THIS specific person, then 3-5 short key themes. Do not invent facts.\n"
        'Return STRICT JSON only: {"work":{"summary":"...","themes":["..."]},'
        '"learning":{"summary":"...","themes":["..."]},'
        '"communication":{"summary":"...","themes":["..."]},'
        '"personal":{"summary":"...","themes":["..."]}}\n\n'
        f"ENTITIES: {ent_line}\n\nCONTEXT:\n{ctx[:6000]}"
    )
    try:
        res = provider.chat([Message(role="user", content=prompt)],
                            temperature=0.4, max_tokens=900)
        data = _extract_json(res.text)
        keymap = {"work": "work", "learning": "learning",
                  "communication": "comm", "personal": "personal"}
        for area, pk in keymap.items():
            d = data.get(area) or {}
            for p in personas:
                if p["key"] == pk:
                    if d.get("summary"):
                        p["summary"] = str(d["summary"]).strip()
                    if isinstance(d.get("themes"), list) and d["themes"]:
                        p["themes"] = [str(t).strip() for t in d["themes"][:5]]
        return {"personas": personas, "generated": True}
    except Exception as exc:
        return {"personas": personas, "generated": False, "error": str(exc)[:160]}


class LeadIn(BaseModel):
    name: str = "Atlas"


@app.post("/api/agents/lead")
def create_lead_agent(body: LeadIn):
    """Create the user's lead agent — head of the team + chief of staff —
    with a system prompt personalised from the brain."""
    from ..agents.custom import get_custom_store
    brain = get_brain()
    name = (body.name or "").strip() or "Atlas"
    ctx = brain.recall(
        "who the user is — their work, projects, interests, the people in "
        "their life, and how they spend their time", limit=16).get("context", "")
    persona = (ctx or "").strip()[:2600]
    system = (
        f"You are {name}, the user's lead agent — the head of their Lodestone team "
        "and their personal chief of staff. You are their first point of contact and "
        "you help with everything: you know their whole world from the shared brain, "
        "you coordinate the specialist agents (Inbox, Launch, Research, Personal), and "
        "you hand off or pull them in when useful. Be warm, concise, and proactive; "
        "when you don't know something, use your tools (search the brain, the web, "
        "tasks, Gmail).\n\n"
        + (f"WHAT YOU ALREADY KNOW ABOUT THE USER:\n{persona}\n" if persona else "")
    )
    a = get_custom_store().create(
        name, "lead agent · chief of staff", system,
        ["search_brain", "remember", "list_entities", "web_search",
         "add_task", "list_tasks", "complete_task", "gmail_search"], [])
    return {"id": a.id, "name": a.name, "role": a.role}


def _fallback_welcome(name: str) -> str:
    return (
        f"Hi — I'm **{name}**, the lead of your Lodestone team. I know your world "
        "from your brain and I'm your first stop for anything. Here's how to get "
        "the most out of Lodestone:\n\n"
        "- **Chat with me** for anything — I'll pull in the specialists (Inbox, "
        "Launch, Research, Personal) when they fit. Switch agents in the left rail.\n"
        "- **Your brain** (right panel) holds your memories and a knowledge graph. "
        "Search it, click an entity for its facts, or *teach it* a new fact anytime.\n"
        "- **Tasks & Automations** let me and the team act for you — capture to-dos "
        "and set things to run on a trigger or schedule.\n"
        "- **Connectors** keep your brain fresh — add more sources whenever you like; "
        "everything stays on your Mac.\n\n"
        "Ask me anything to get started — try *“what should I focus on today?”*"
    )


@app.post("/api/agents/{agent_id}/welcome")
def agent_welcome(agent_id: str, body: ChatIn | None = None):
    """A one-time, personalised welcome from an agent that introduces itself and
    teaches the app. Generated fresh (not persisted to chat history)."""
    from ..agents.presets import get_agent
    from ..models.registry import get_provider
    from ..models.base import Message
    try:
        agent = get_agent(agent_id)
    except KeyError:
        raise HTTPException(404, f"unknown agent '{agent_id}'")
    s = get_settings()
    provider = get_provider((body.provider if body else None) or s.model_provider,
                            (body.model if body else None) or s.model_name)
    try:
        ready, _ = provider.is_ready()
    except Exception:
        ready = False
    if not ready:
        return {"reply": _fallback_welcome(agent.name)}
    seed = (
        "You are meeting the user for the very first time as their lead agent. "
        "Write a warm welcome that: (1) greets them and introduces yourself in 1-2 "
        "sentences using what you already know about them from the brain (be specific "
        "but natural); (2) teaches them how to use Lodestone in short skimmable "
        "bullet points — chatting with you and switching to the specialist agents "
        "(Inbox, Launch, Research, Personal); the Brain panel (memories, the knowledge "
        "graph, and teaching it new facts); Tasks and Automations; and connecting more "
        "sources (all on-device). End by inviting them to ask you anything. Use Markdown."
    )
    try:
        res = provider.chat([Message(role="system", content=agent.system_message()),
                             Message(role="user", content=seed)],
                            temperature=0.5, max_tokens=700)
        return {"reply": (res.text or "").strip() or _fallback_welcome(agent.name)}
    except Exception:
        return {"reply": _fallback_welcome(agent.name)}


@app.get("/api/brain/entities")
def entities(limit: int = 30):
    return {"entities": get_brain().graph.top_entities(limit=limit)}

@app.get("/api/brain/entities/{entity_id}/facts")
def entity_facts(entity_id: str):
    g = get_brain().graph
    row = g._conn.execute(
        "SELECT id,name,type,summary,mentions FROM entities WHERE id=?",
        (entity_id,)).fetchone()
    if not row:
        raise HTTPException(404, "entity not found")
    return {"entity": dict(row), "facts": g.facts_for(entity_id, limit=15)}

@app.get("/api/brain/search")
def brain_search(q: str, limit: int = 20):
    hits = get_brain().store.search(q, limit=limit)
    return {"memories": [{"score": h.score, **h.memory.model_dump()} for h in hits]}

@app.post("/api/brain/ingest")
def ingest(body: IngestIn):
    out = get_brain().ingest(body.text, source=body.source, title=body.title)
    return out

@app.post("/api/brain/recall")
def recall(body: ChatIn):
    return get_brain().recall(body.message)

@app.get("/api/brain/export")
def brain_export():
    """Download the whole brain as a portable JSON backup (you own your data)."""
    import json as _json
    from datetime import datetime
    data = get_brain().export()
    stamp = datetime.now().strftime("%Y%m%d")
    return Response(
        content=_json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="lodestone-brain-{stamp}.json"'})

class ImportIn(BaseModel):
    memories: list[dict[str, Any]] = []
    lodestone_backup: int | None = None

@app.post("/api/brain/import")
def brain_import(body: ImportIn):
    """Restore memories from an exported backup. Idempotent (dedup)."""
    return get_brain().import_data(body.model_dump())


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
        if not cls.supported_here():
            continue                      # hide macOS-only connectors off macOS
        inst = cls()
        ready, reason = inst.is_configured()
        out.append({"name": name, "label": cls.label, "ready": ready,
                    "reason": reason, "always_available": cls.always_available,
                    "secret_field": cls.secret_field, "custom": False,
                    "state": state.get(name)})
    # user-defined custom API apps
    from ..connectors.custom_api import CustomAPIConnector, list_apps
    for app in list_apps():
        inst = CustomAPIConnector(app)
        ready, reason = inst.is_configured()
        out.append({"name": inst.name, "label": inst.label, "ready": ready,
                    "reason": reason, "always_available": False,
                    "secret_field": None, "custom": True, "config": app,
                    "state": state.get(inst.name)})
    return {"connectors": out}

# ── custom apps (connect any REST app, no code) ───────────────────────────
class CustomAppIn(BaseModel):
    id: str | None = None
    name: str = "Custom app"
    base_url: str = ""
    endpoint: str = ""
    auth_type: str = "none"      # none | bearer | header | query
    auth_name: str = ""
    token: str | None = None
    items_path: str = ""
    title_field: str = ""
    body_field: str = ""

@app.get("/api/custom-apps")
def custom_apps():
    from ..connectors.custom_api import list_apps
    return {"apps": list_apps()}

@app.post("/api/custom-apps")
def save_custom_app(body: CustomAppIn):
    from ..connectors.custom_api import upsert_app
    url = (body.base_url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(422, "base URL must start with http:// or https://")
    cfg = body.model_dump()
    token = cfg.pop("token", None)
    app = upsert_app(cfg, token=token)
    return {"saved": True, "app": app, "name": f"custom:{app['id']}"}

@app.delete("/api/custom-apps/{app_id}")
def delete_custom_app(app_id: str):
    from ..connectors.custom_api import delete_app
    return {"deleted": delete_app(app_id)}

class SecretIn(BaseModel):
    value: str = ""

@app.post("/api/connectors/{name}/secret")
def save_connector_secret(name: str, body: SecretIn):
    """Save (or clear) a connector's single-token secret from the UI —
    no .env editing. Written to ~/Library/Lodestone/secrets.json (chmod 600)."""
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise HTTPException(404, f"unknown connector '{name}'")
    field = cls.secret_field
    if not field:
        raise HTTPException(400, f"'{name}' does not use a token secret")
    get_settings().set_secret(field["key"], body.value)
    ready, reason = cls().is_configured()
    return {"saved": True, "ready": ready, "reason": reason}


@app.post("/api/providers/{name}/key")
def save_provider_key(name: str, body: SecretIn):
    """Save (or clear) an LLM provider's API key from the UI — stored locally in
    ~/Library/Lodestone/secrets.json and picked up by the provider on next use."""
    from ..models.registry import _REGISTRY
    cls = _REGISTRY.get(name)
    if cls is None:
        raise HTTPException(404, f"unknown provider '{name}'")
    key_env = getattr(cls, "key_env", None)
    if not key_env:
        raise HTTPException(400, f"'{name}' does not use an API key")
    get_settings().set_secret(key_env, body.value or None)
    try:
        ready, reason = cls().is_ready()
    except Exception as exc:
        ready, reason = False, str(exc)[:120]
    return {"saved": True, "ready": ready, "reason": reason}

@app.post("/api/connectors/{name}/sync")
def sync(name: str, body: SyncIn):
    try:
        conn = get_connector(name)
    except KeyError:
        raise HTTPException(404, f"unknown connector '{name}'")
    # route ingestion through the brain so the graph is built too
    res = conn.sync(**body.params)
    return res.as_dict()


# ── Google sign-in (bundled client → no per-user Cloud setup) ─────────────
@app.get("/api/google/status")
def google_status():
    from ..connectors.google_auth import (_token_path, connected_email,
                                           granted_services)
    connected = _token_path().exists()
    return {"client_configured": get_settings().google_client_secrets is not None,
            "connected": connected,
            "account": connected_email(fetch=connected) if connected else None,
            "services": granted_services()}

@app.post("/api/google/disconnect")
def google_disconnect():
    from ..connectors.google_auth import disconnect
    disconnect()
    return {"disconnected": True}

# ── Google reconnect (re-consent with current scopes, from the UI) ────────
@app.post("/api/google/reconnect")
def google_reconnect():
    import threading
    from ..connectors.google_auth import _token_path, get_credentials
    tok = _token_path()
    if tok.exists():
        tok.unlink()
    # opens the Google consent browser on this machine; runs in the background
    threading.Thread(
        target=lambda: get_credentials(interactive=True), daemon=True).start()
    return {"started": True,
            "detail": "A browser window is opening — approve the permissions."}


# ── actions (execute only after explicit user confirmation) ───────────────
class ActionIn(BaseModel):
    type: str
    params: dict[str, Any] = {}

@app.post("/api/actions/execute")
def execute_action(body: ActionIn):
    from ..actions import execute
    return execute(body.type, body.params)


class NewRoutine(BaseModel):
    name: str
    agent_id: str = "personal"
    trigger: str = "new_email"          # new_email | schedule
    instruction: str
    interval_min: int = 60

@app.get("/api/routines")
def list_routines():
    from ..routines import get_routines
    return {"routines": get_routines().list()}

@app.post("/api/routines")
def create_routine(body: NewRoutine):
    from ..routines import get_routines
    return get_routines().create(body.name, body.agent_id, body.trigger,
                                 body.instruction, body.interval_min)

@app.post("/api/routines/{rid}/toggle")
def toggle_routine(rid: str, on: bool = True):
    from ..routines import get_routines
    get_routines().toggle(rid, on)
    return {"ok": True}

@app.delete("/api/routines/{rid}")
def delete_routine(rid: str):
    from ..routines import get_routines
    return {"deleted": get_routines().delete(rid)}


@app.get("/api/reminders")
def list_reminders():
    import json as _json
    from ..reminders import get_reminders
    from ..scheduled import get_scheduled
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

@app.delete("/api/reminders/{rid}")
def delete_reminder(rid: str):
    from ..reminders import get_reminders
    from ..scheduled import get_scheduled
    ok = get_reminders().delete(rid) or get_scheduled().delete(rid)
    return {"deleted": ok}


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


@app.get("/onboarding")
def onboarding():
    return FileResponse(WEB / "onboarding.html")

app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


def run() -> None:
    import uvicorn
    s = get_settings()
    print(f"\n  ◆ Lodestone workspace → http://{s.host}:{s.port}")
    print(f"    model: {s.model_provider}   brain: {s.home}\n")
    uvicorn.run(app, host=s.host, port=s.port, log_level="info")
