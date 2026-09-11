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
@app.get("/api/models/catalog")
def models_catalog(refresh: bool = False):
    from ..models.registry import get_model_catalog
    return {"catalog": get_model_catalog(force_refresh=refresh)}


@app.get("/api/agents")
def agents():
    from ..agents.presets import PRESETS
    mem = AgentMemory()
    return {"agents": [
        {"id": a.id, "name": a.name, "role": a.role, "tools": a.tools,
         "custom": a.id not in PRESETS,
         "model_provider": a.model_provider,
         "model_name": a.model_name,
         "messages": len(mem.history(a.id, limit=1000))}
        for a in list_agents()
    ]}


@app.get("/api/agents/{agent_id}/history")
def history(agent_id: str):
    return {"history": AgentMemory().history(agent_id, limit=100)}


class AgentModelIn(BaseModel):
    provider: str
    model: str | None = None


@app.get("/api/agents/{agent_id}/model")
def get_agent_model_endpoint(agent_id: str):
    from ..agents.agent_models import get_agent_model
    from ..agents.presets import get_agent
    try:
        agent = get_agent(agent_id)
    except KeyError:
        raise HTTPException(404, f"unknown agent '{agent_id}'")
    prov, model = get_agent_model(agent_id)
    s = get_settings()
    is_override = prov is not None
    effective_provider = prov or s.model_provider or "mock"
    if prov is not None:
        if model:
            effective_model = model
        else:
            from ..models.registry import MODEL_CATALOG
            cat = MODEL_CATALOG.get(prov, {})
            effective_model = cat.get("default_model") or ""
    else:
        effective_model = model or s.model_name or ""
    return {
        "agent_id": agent_id,
        "provider": effective_provider,
        "model": effective_model,
        "configured_provider": prov,
        "configured_model": model,
        "is_override": is_override,
    }


@app.post("/api/agents/{agent_id}/model")
@app.put("/api/agents/{agent_id}/model")
def set_agent_model_endpoint(agent_id: str, body: AgentModelIn):
    from ..agents.agent_models import set_agent_model
    from ..agents.presets import get_agent
    try:
        get_agent(agent_id)
    except KeyError:
        raise HTTPException(404, f"unknown agent '{agent_id}'")
    return set_agent_model(agent_id, body.provider, body.model)


@app.delete("/api/agents/{agent_id}/model")
def clear_agent_model_endpoint(agent_id: str):
    from ..agents.agent_models import clear_agent_model
    from ..agents.presets import get_agent
    try:
        get_agent(agent_id)
    except KeyError:
        raise HTTPException(404, f"unknown agent '{agent_id}'")
    cleared = clear_agent_model(agent_id)
    return {"cleared": cleared}


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


class FlagIn(BaseModel):
    value: bool = True


@app.get("/api/onboarded")
def get_onboarded():
    """Server-side onboarding flag — survives the desktop app's per-launch port
    (localStorage is per-origin, so it would reset every launch)."""
    return {"onboarded": get_brain().store.get_meta("onboarded") == "1"}


@app.post("/api/onboarded")
def set_onboarded(body: FlagIn | None = None):
    get_brain().store.set_meta("onboarded", "1" if (body is None or body.value) else "0")
    return {"onboarded": body is None or body.value}


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
        try:
            out["canonical"] = _canon().reset()
        except Exception:
            pass
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


class EnrichIn(BaseModel):
    # A dedicated ENRICHMENT model, independent of the chat/agent model — the UI can
    # point enrichment at a cheap/local model while agents use a stronger one.
    provider: str | None = None
    model: str | None = None


@app.post("/api/brain/enrich")
def brain_enrich(body: EnrichIn | None = None):
    """One small batch (kept for compatibility / manual stepping)."""
    p = body.provider if body else None
    m = body.model if body else None
    return get_brain().enrich(limit=8, provider_name=p, model_name=m)


@app.post("/api/brain/enrich/start")
def brain_enrich_start(body: EnrichIn | None = None):
    """Start (or return) a SERVER-SIDE enrichment job that drains the queue in the
    background — so a frontend refresh reconnects to it instead of stopping it."""
    p = body.provider if body else None
    m = body.model if body else None
    return get_brain().start_enrich(provider_name=p, model_name=m)


@app.post("/api/brain/enrich/stop")
def brain_enrich_stop():
    return get_brain().stop_enrich()


@app.get("/api/brain/enrich/status")
def brain_enrich_status():
    return get_brain().enrich_status()


class EnrichCapIn(BaseModel):
    cap: int = Field(ge=0, le=100000)


@app.get("/api/brain/enrich/config")
def brain_enrich_config():
    b = get_brain()
    return {"cap": b.enrich_cap(), "remaining": b._queue_count(),
            "full_sources": list(b._FULL_SOURCES)}


@app.post("/api/brain/enrich/config")
def brain_set_enrich_config(body: EnrichCapIn):
    """Cap how many of the most-recent items PER BULK SOURCE (Gmail, Drive, …) get
    LLM-enriched. 0 = unlimited. High-signal sources are always enriched in full."""
    return get_brain().set_enrich_cap(body.cap)


@app.get("/api/usage")
def usage_get():
    """Cumulative LLM token usage (persisted). Includes a context-window 'limit'
    for the active model when known."""
    from .. import usage as _usage
    from ..models.registry import context_window, _LOCALITY
    s = get_settings()
    data = _usage.get()
    active = data["by_provider"].get(s.model_provider, {})
    ctx = context_window(active.get("model") or s.model_name)
    locality = _LOCALITY.get(s.model_provider, ("cloud", ""))[0]
    return {"total": data["total"], "by_provider": data["by_provider"],
            "active_provider": s.model_provider, "active": active,
            "context_window": ctx, "locality": locality, "updated": data["updated"]}


@app.post("/api/usage/reset")
def usage_reset():
    from .. import usage as _usage
    _usage.reset()
    return {"reset": True}


@app.post("/api/brain/rebuild")
def brain_rebuild():
    """Wipe the graph and re-queue every memory, then refill it in the background
    with the free offline extractor (cleans out junk, no model tokens)."""
    import threading
    out = get_brain().rebuild_graph()
    threading.Thread(target=lambda: get_brain().enrich_until_done(fast=True),
                     daemon=True).start()
    return out


@app.post("/api/brain/prune")
def brain_prune():
    """Sweep out junk entities that fail the current quality filter (and their
    facts), keeping all good graph work. Cheap — no rebuild, no model tokens."""
    return get_brain().prune()


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

# ── Brain v1.5 Open Loops, Inspection, Contradictions, and Evaluation ───────
class OpenLoopIn(BaseModel):
    description: str
    due_at: str | None = None
    priority: str = "medium"
    related_project: str | None = None
    related_entities: list[str] = []

@app.get("/api/brain/open-loops")
def get_open_loops(status: str | None = "open", project: str | None = None):
    return {"open_loops": get_brain().get_open_loops(status=status, related_project=project)}

@app.post("/api/brain/open-loops")
def create_open_loop(body: OpenLoopIn):
    loop = get_brain().create_open_loop(
        description=body.description,
        due_at=body.due_at,
        priority=body.priority,
        related_project=body.related_project,
        related_entities=body.related_entities,
    )
    return {"open_loop": loop}

@app.post("/api/brain/open-loops/{loop_id}/complete")
def complete_open_loop(loop_id: str):
    done = get_brain().complete_open_loop(loop_id)
    if not done:
        raise HTTPException(404, "open loop not found")
    return {"open_loop": done}

@app.get("/api/brain/memories/{memory_id}")
def get_memory(memory_id: str):
    mem = get_brain().inspect_memory(memory_id)
    if not mem:
        raise HTTPException(404, "memory not found")
    return {"memory": mem}

@app.get("/api/brain/memories/{memory_id}/explain")
def explain_memory(memory_id: str, q: str = ""):
    exp = get_brain().explain_memory(memory_id, query=q)
    if "error" in exp:
        raise HTTPException(404, exp["error"])
    return exp

@app.get("/api/brain/contradictions")
def get_contradictions():
    return {"contradictions": get_brain().detect_contradictions()}

class ResolveConflictIn(BaseModel):
    conflict: dict[str, Any]
    auto_supersede: bool = True

@app.post("/api/brain/contradictions/resolve")
def resolve_contradiction(body: ResolveConflictIn):
    return get_brain().resolve_contradiction(body.conflict, auto_supersede=body.auto_supersede)

@app.get("/api/brain/evaluate")
def evaluate_brain():
    return get_brain().evaluate_quality()

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


# ── canonical Brain (curated, source-backed model of the user) ─────────────
def _canon():
    from ..brain.canonical import get_canonical
    return get_canonical()


class RememberIn(BaseModel):
    text: str
    provider: str | None = None
    model: str | None = None


@app.get("/api/brain/canonical")
def canonical_overview():
    """The four user-visible sections + stats."""
    cb = _canon()
    return {
        "stats": cb.stats(),
        "about_you": cb.about_you(),
        "people": cb.people(),
        "work": cb.work(),
        "timeline": cb.timeline(limit=100),
    }

@app.post("/api/brain/canonical/remember")
def canonical_remember(body: RememberIn):
    """Explicit 'remember this' → candidate → trust rules → canonical."""
    return _canon().remember(body.text, provider_name=body.provider,
                             model_name=body.model)

@app.get("/api/brain/canonical/review")
def canonical_review():
    return {"pending": _canon().pending()}

@app.post("/api/brain/canonical/review/{candidate_id}/approve")
def canonical_approve(candidate_id: str):
    return _canon().approve(candidate_id)

class RejectIn(BaseModel):
    reason: str = ""

@app.post("/api/brain/canonical/review/{candidate_id}/reject")
def canonical_reject(candidate_id: str, body: RejectIn):
    return _canon().reject(candidate_id, body.reason)

@app.post("/api/brain/canonical/maintain")
def canonical_maintain():
    """Freshness maintenance pass (mark aging/stale current claims)."""
    return _canon().maintain()

@app.post("/api/brain/canonical/export")
def canonical_export():
    """Regenerate the Markdown/JSON mirror under ~/Library/Lodestone/brain-export."""
    return _canon().export()

@app.get("/api/brain/canonical/evaluate")
def canonical_evaluate(k: int = 5):
    return _canon().evaluate(k=k)

# NOTE: keep this parametrized GET last — it must not shadow the specific
# /review and /evaluate GET routes above.
@app.get("/api/brain/canonical/{section}")
def canonical_section(section: str):
    cb = _canon()
    fn = {"about_you": cb.about_you, "people": cb.people,
          "work": cb.work, "timeline": cb.timeline}.get(section)
    if not fn:
        raise HTTPException(404, f"unknown section '{section}'")
    return {"section": section, "records": fn()}


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


@app.get("/api/providers/capabilities")
def get_provider_capabilities_endpoint():
    from ..models.capabilities import list_capabilities
    return {"capabilities": list_capabilities()}


@app.get("/api/providers/connections")
def get_provider_connections_endpoint():
    from ..models.connections import list_connections
    return {"connections": [c.to_dict() for c in list_connections()]}


@app.get("/api/providers/detected-accounts")
def get_detected_accounts_endpoint():
    from ..models.accounts import detect_all_accounts
    return {"accounts": detect_all_accounts()}


@app.post("/api/providers/{name}/connect-local")
def connect_local_provider_endpoint(name: str):
    from ..models.accounts import connect_local_account
    from ..models.registry import clear_provider_cache
    ok, msg, data = connect_local_account(name)
    if not ok:
        raise HTTPException(400, msg)
    clear_provider_cache()
    return {"ok": True, "message": msg, "connection": data}


@app.post("/api/providers/{name}/signin")
def signin_provider_endpoint(name: str):
    from ..models.accounts import connect_local_account, detect_all_accounts
    from ..models.capabilities import get_capabilities
    from ..models.registry import clear_provider_cache

    pid = name.lower()
    if pid in ("gemini", "google"):
        return google_reconnect()

    caps = get_capabilities(pid)
    url = caps.official_auth_url if caps else ""

    if pid in ("claude", "anthropic"):
        from ..models.claude_auth import start_claude_login_flow, find_claude_cli
        ok, auth_url, msg = start_claude_login_flow()
        has_cli = bool(find_claude_cli())
        return {
            "started": True,
            "provider_id": "claude",
            "auth_url": auth_url,
            "brand_name": "Claude",
            "requires_code": True,
            "browser_opened": bool(ok and has_cli),
            "detail": "Opened Claude authorization in browser — sign in to your account.",
        }

    elif pid == "cursor":
        auth_url = "https://cursor.com/login"
        return {
            "started": True,
            "provider_id": "cursor",
            "auth_url": auth_url,
            "brand_name": "Cursor",
            "browser_opened": False,
            "detail": "Opened Cursor in browser — sign in to your Cursor account.",
        }

    elif pid == "openai":
        from ..models.chatgpt_auth import start_chatgpt_oauth_flow, find_codex_cli
        ok, auth_url, msg = start_chatgpt_oauth_flow()
        has_cli = bool(find_codex_cli())
        return {
            "started": True,
            "provider_id": "openai",
            "auth_url": auth_url,
            "brand_name": "ChatGPT",
            "browser_opened": bool(ok and has_cli),
            "detail": "Opened ChatGPT sign-in in browser — choose your account to continue to Codex.",
        }

    elif pid in ("xai", "grok"):
        from ..models.xai_auth import start_xai_oauth_flow
        ok, auth_url, msg = start_xai_oauth_flow()
        return {
            "started": True,
            "provider_id": "xai",
            "auth_url": auth_url,
            "brand_name": "Grok",
            "browser_opened": False,
            "detail": "Opened Grok sign-in in browser — log in to your account.",
        }

    elif url:
        return {"started": True, "auth_url": url, "browser_opened": False, "detail": f"Opened {caps.display_name if caps else pid} in browser."}

    return {"started": True, "detail": "Please sign in to your provider."}


@app.get("/api/providers/openai/oauth-status")
def openai_oauth_status_endpoint():
    from ..models.chatgpt_auth import get_oauth_flow_status
    return get_oauth_flow_status()


@app.get("/api/providers/xai/oauth-status")
def xai_oauth_status_endpoint():
    from ..models.xai_auth import get_xai_oauth_flow_status
    return get_xai_oauth_flow_status()


@app.get("/api/providers/claude/oauth-status")
def claude_oauth_status_endpoint():
    from ..models.claude_auth import get_claude_auth_status
    return get_claude_auth_status()


@app.post("/api/providers/claude/submit-code")
def claude_submit_code_endpoint(payload: dict):
    from ..models.claude_auth import submit_claude_auth_code
    code = payload.get("code", "").strip()
    if not code:
        raise HTTPException(400, "code is required")
    ok, msg = submit_claude_auth_code(code)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg}



@app.get("/api/providers/{name}/models")
def get_provider_models_endpoint(name: str, refresh: bool = False):
    from ..models.discovery import get_discovered_models
    models, meta = get_discovered_models(name, force_refresh=refresh)
    return {"models": models, "account_meta": meta}


@app.post("/api/providers/{name}/refresh")
def refresh_provider_endpoint(name: str):
    from datetime import datetime, timezone
    from ..models.capabilities import get_capabilities
    from ..models.connections import ConnectionStatus, get_connection, save_connection
    from ..models.discovery import get_discovered_models
    from ..models.registry import _REGISTRY, clear_provider_cache

    cls = _REGISTRY.get(name)
    if cls is None:
        raise HTTPException(404, f"unknown provider '{name}'")
    clear_provider_cache()
    inst = cls()
    ready, reason = inst.is_ready()
    models, account_meta = get_discovered_models(name, force_refresh=True)

    caps = get_capabilities(name)
    conn = get_connection(name)
    now = datetime.now(timezone.utc).isoformat()
    conn.last_verified_at = now
    conn.status_message = reason or ("Connected & ready" if ready else "")

    if ready:
        if conn.connection_status in (ConnectionStatus.NOT_CONNECTED, ConnectionStatus.DISCONNECTED, ConnectionStatus.ERROR):
            conn.connection_status = ConnectionStatus.API_KEY_CONNECTED if (caps and caps.api_key_supported) else ConnectionStatus.CONNECTED
        if not conn.connected_at:
            conn.connected_at = now
    else:
        if conn.connection_status != ConnectionStatus.DISCONNECTED:
            conn.connection_status = ConnectionStatus.NOT_CONNECTED

    if account_meta.get("email"):
        conn.email = account_meta["email"]
    if account_meta.get("name"):
        conn.account_display_name = account_meta["name"]
    if account_meta.get("account_id"):
        conn.account_id = account_meta["account_id"]

    save_connection(conn)
    return {
        "ok": True,
        "ready": ready,
        "reason": reason,
        "connection": conn.to_dict(),
        "models": models,
        "account_meta": account_meta,
    }


@app.post("/api/providers/{name}/disconnect")
def disconnect_provider_endpoint(name: str):
    from datetime import datetime, timezone
    from ..models.connections import ConnectionStatus, get_connection, save_connection
    from ..models.registry import _REGISTRY, clear_provider_cache

    cls = _REGISTRY.get(name)
    if cls is None:
        raise HTTPException(404, f"unknown provider '{name}'")
    key_env = getattr(cls, "key_env", None)
    if key_env:
        get_settings().set_secret(key_env, None)
    clear_provider_cache()

    conn = get_connection(name)
    conn.connection_status = ConnectionStatus.DISCONNECTED
    conn.status_message = "Disconnected by user"
    conn.last_verified_at = datetime.now(timezone.utc).isoformat()
    save_connection(conn)
    return {"disconnected": True, "connection": conn.to_dict()}


@app.post("/api/providers/{name}/key")
def save_provider_key(name: str, body: SecretIn):
    """Save (or clear) an LLM provider's API key from the UI — stored locally in
    ~/Library/Lodestone/secrets.json and picked up by the provider on next use."""
    from datetime import datetime, timezone
    from ..models.connections import ConnectionStatus, get_connection, save_connection
    from ..models.discovery import get_discovered_models
    from ..models.registry import _REGISTRY, clear_provider_cache

    cls = _REGISTRY.get(name)
    if cls is None:
        raise HTTPException(404, f"unknown provider '{name}'")
    key_env = getattr(cls, "key_env", None)
    if not key_env:
        raise HTTPException(400, f"'{name}' does not use an API key")

    val = body.value.strip() if body.value else ""
    get_settings().set_secret(key_env, val or None)
    clear_provider_cache()

    conn = get_connection(name)
    now = datetime.now(timezone.utc).isoformat()
    conn.last_verified_at = now
    conn.credential_reference = key_env

    if not val:
        conn.connection_status = ConnectionStatus.DISCONNECTED
        conn.status_message = "API key removed"
        save_connection(conn)
        return {"saved": True, "ready": False, "reason": f"set {key_env}", "connection": conn.to_dict()}

    try:
        inst = cls(api_key=val)
        ready, reason = inst.is_ready()
    except Exception as exc:
        ready, reason = False, str(exc)[:120]

    if ready:
        conn.connection_status = ConnectionStatus.API_KEY_CONNECTED
        conn.connected_at = now
        conn.status_message = "Connected via API key"
        # Discover models & identity with new key
        try:
            _, meta = get_discovered_models(name, force_refresh=True, api_key=val)
            if meta.get("email"):
                conn.email = meta["email"]
            if meta.get("name"):
                conn.account_display_name = meta["name"]
            if meta.get("account_id"):
                conn.account_id = meta["account_id"]
        except Exception:
            pass
    else:
        conn.connection_status = ConnectionStatus.ERROR
        conn.status_message = reason

    save_connection(conn)
    return {"saved": True, "ready": ready, "reason": reason, "connection": conn.to_dict()}


@app.post("/api/providers/{name}/test")
def test_provider_key(name: str, body: SecretIn | None = None):
    """Test / verify an LLM provider connection with either a test key or saved key."""
    from ..models.registry import _REGISTRY
    cls = _REGISTRY.get(name)
    if cls is None:
        raise HTTPException(404, f"unknown provider '{name}'")
    test_key = body.value if (body and body.value is not None) else None
    try:
        inst = cls(api_key=test_key)
        ready, reason = inst.is_ready()
        if not ready:
            return {"ok": False, "message": reason}
        return {"ok": True, "message": f"{name} is connected and ready!"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:180]}


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
    from ..models.connections import ConnectionStatus, get_connection, save_connection
    connected = _token_path().exists()
    account = connected_email(fetch=connected) if connected else None
    if connected and account:
        conn = get_connection("gemini")
        if conn.connection_status != ConnectionStatus.ACCOUNT_CONNECTED or conn.email != account:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            conn.auth_method = "account"
            conn.email = account
            conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
            conn.connected_at = conn.connected_at or now
            conn.last_verified_at = now
            conn.status_message = "Connected Google account"
            save_connection(conn)
    return {"client_configured": get_settings().google_client_secrets is not None,
            "connected": connected,
            "account": account,
            "services": granted_services()}

@app.post("/api/google/disconnect")
def google_disconnect():
    from ..connectors.google_auth import disconnect
    from ..models.connections import ConnectionStatus, get_connection, save_connection
    disconnect()
    conn = get_connection("gemini")
    if conn.auth_method == "account":
        conn.connection_status = ConnectionStatus.DISCONNECTED
        conn.status_message = "Google account disconnected"
        save_connection(conn)
    return {"disconnected": True}

# ── Google reconnect (re-consent with current scopes, from the UI) ────────
@app.post("/api/google/reconnect")
def google_reconnect():
    import threading
    from ..connectors.google_auth import _token_path, get_credentials, connected_email
    from ..models.connections import ConnectionStatus, get_connection, save_connection
    tok = _token_path()
    if tok.exists():
        tok.unlink()
    
    def _run():
        try:
            creds = get_credentials(interactive=True)
            email = connected_email(fetch=True)
            conn = get_connection("gemini")
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            conn.auth_method = "account"
            conn.email = email
            conn.connection_status = ConnectionStatus.ACCOUNT_CONNECTED
            conn.connected_at = conn.connected_at or now
            conn.last_verified_at = now
            conn.status_message = "Connected Google account"
            save_connection(conn)
        except Exception:
            pass

    # opens the Google consent browser on this machine; runs in the background
    threading.Thread(target=_run, daemon=True).start()
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


def run(reload: bool = False) -> None:
    import uvicorn
    s = get_settings()
    print(f"\n  ◆ Lodestone workspace → http://{s.host}:{s.port}")
    print(f"    model: {s.model_provider}   brain: {s.home}"
          + ("   (dev: backend auto-reloads)" if reload else "") + "\n")
    if reload:
        # watch the package so edits to any .py hot-reload the server
        uvicorn.run("lodestone.api.app:app", host=s.host, port=s.port, reload=True,
                    reload_dirs=[str(Path(__file__).resolve().parent.parent)],
                    log_level="info")
    else:
        uvicorn.run(app, host=s.host, port=s.port, log_level="info")
