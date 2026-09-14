"""The brain — memories, the knowledge graph, enrichment, and the canonical layer."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ...brain import get_brain
from ...config import get_settings
from ...connectors import REGISTRY
from ...log import get_logger, suppressed
from ..concurrency import calls_a_model
from ..schemas import ChatIn

log = get_logger(__name__)
router = APIRouter()


class IngestIn(BaseModel):
    text: str = Field(max_length=200000)
    title: str | None = None
    source: str = "notes"


# ── brain ─────────────────────────────────────────────────────────────────
@router.get("/api/brain/stats")
def brain_stats():
    return get_brain().stats()


class FlagIn(BaseModel):
    value: bool = True


@router.get("/api/onboarded")
def get_onboarded():
    """Server-side onboarding flag — survives the desktop app's per-launch port
    (localStorage is per-origin, so it would reset every launch)."""
    return {"onboarded": get_brain().store.get_meta("onboarded") == "1"}


@router.post("/api/onboarded")
def set_onboarded(body: FlagIn | None = None):
    get_brain().store.set_meta("onboarded", "1" if (body is None or body.value) else "0")
    return {"onboarded": body is None or body.value}


class ResetIn(BaseModel):
    memories: bool = True   # wipe all memories + graph + connector state
    secrets: bool = True    # forget saved connector tokens (Notion/GitHub/Linear…)
    google: bool = True     # sign out of Google (so onboarding re-consents)


@router.post("/api/brain/reset")
def brain_reset(body: ResetIn | None = None):
    """Start-from-zero: wipe the brain and, optionally, forget every connector
    credential so the onboarding flow reconnects each source from scratch."""
    body = body or ResetIn()
    out: dict[str, Any] = {}
    if body.memories:
        out.update(get_brain().reset())
        with suppressed("out['canonical'] = _canon().reset()"):
            out["canonical"] = _canon().reset()
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
            from ...connectors.google_auth import disconnect
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


@router.post("/api/brain/digest")
@calls_a_model
def brain_digest(body: ChatIn | None = None):
    """The 'Here's your brain' digest — real, LLM-written second-person personas
    grounded in the user's actual brain. Uses the caller's chosen model (falling
    back to the server default), and to counts + themes when there is no data yet
    or no model is connected."""
    from ...models.base import Message
    from ...models.registry import get_provider
    personas = _base_personas()
    brain = get_brain()
    total = brain.stats().get("total", 0)
    s = get_settings()
    p_name = (body.provider if body else None) or s.model_provider
    m_name = (body.model if body else None)
    # Only fall back to settings.model_name when provider matches — prevents
    # leaking e.g. an Ollama model name into Gemini.
    if not m_name and p_name == s.model_provider:
        m_name = s.model_name
    provider = get_provider(p_name, m_name)
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


class EnrichIn(BaseModel):
    # A dedicated ENRICHMENT model, independent of the chat/agent model — the UI can
    # point enrichment at a cheap/local model while agents use a stronger one.
    provider: str | None = None
    model: str | None = None


@router.post("/api/brain/enrich")
@calls_a_model
def brain_enrich(body: EnrichIn | None = None):
    """One small batch (kept for compatibility / manual stepping)."""
    p = body.provider if body else None
    m = body.model if body else None
    return get_brain().enrich(limit=8, provider_name=p, model_name=m)


@router.post("/api/brain/enrich/start")
def brain_enrich_start(body: EnrichIn | None = None):
    """Start (or return) a SERVER-SIDE enrichment job that drains the queue in the
    background — so a frontend refresh reconnects to it instead of stopping it."""
    p = body.provider if body else None
    m = body.model if body else None
    return get_brain().start_enrich(provider_name=p, model_name=m)


@router.post("/api/brain/enrich/stop")
def brain_enrich_stop():
    return get_brain().stop_enrich()


@router.get("/api/brain/enrich/status")
def brain_enrich_status():
    return get_brain().enrich_status()


class EnrichCapIn(BaseModel):
    cap: int = Field(ge=0, le=100000)


@router.get("/api/brain/enrich/config")
def brain_enrich_config():
    b = get_brain()
    return {"cap": b.enrich_cap(), "remaining": b._queue_count(),
            "full_sources": list(b._FULL_SOURCES)}


@router.post("/api/brain/enrich/config")
def brain_set_enrich_config(body: EnrichCapIn):
    """Cap how many of the most-recent items PER BULK SOURCE (Gmail, Drive, …) get
    LLM-enriched. 0 = unlimited. High-signal sources are always enriched in full."""
    return get_brain().set_enrich_cap(body.cap)


@router.post("/api/brain/rebuild")
def brain_rebuild():
    """Wipe the graph and re-queue every memory, then refill it in the background
    with the free offline extractor (cleans out junk, no model tokens)."""
    import threading
    out = get_brain().rebuild_graph()
    threading.Thread(target=lambda: get_brain().enrich_until_done(fast=True),
                     daemon=True).start()
    return out


@router.post("/api/brain/prune")
def brain_prune():
    """Sweep out junk entities that fail the current quality filter (and their
    facts), keeping all good graph work. Cheap — no rebuild, no model tokens."""
    return get_brain().prune()


@router.get("/api/brain/entities")
def entities(limit: int = 30):
    return {"entities": get_brain().graph.top_entities(limit=limit)}


@router.get("/api/brain/entities/{entity_id}/facts")
def entity_facts(entity_id: str):
    g = get_brain().graph
    row = g._conn.execute(
        "SELECT id,name,type,summary,mentions FROM entities WHERE id=?",
        (entity_id,)).fetchone()
    if not row:
        raise HTTPException(404, "entity not found")
    return {"entity": dict(row), "facts": g.facts_for(entity_id, limit=15)}


@router.get("/api/brain/search")
def brain_search(q: str, limit: int = 20):
    hits = get_brain().store.search(q, limit=limit)
    return {"memories": [{"score": h.score, **h.memory.model_dump()} for h in hits]}


@router.post("/api/brain/ingest")
def ingest(body: IngestIn):
    return get_brain().ingest(body.text, source=body.source, title=body.title)


@router.post("/api/brain/recall")
def recall(body: ChatIn):
    return get_brain().recall(body.message)


# ── Brain v1.5 Open Loops, Inspection, Contradictions, and Evaluation ───────
class OpenLoopIn(BaseModel):
    description: str
    due_at: str | None = None
    priority: str = "medium"
    related_project: str | None = None
    related_entities: list[str] = []


@router.get("/api/brain/open-loops")
def get_open_loops(status: str | None = "open", project: str | None = None):
    return {"open_loops": get_brain().get_open_loops(status=status, related_project=project)}


@router.post("/api/brain/open-loops")
def create_open_loop(body: OpenLoopIn):
    loop = get_brain().create_open_loop(
        description=body.description,
        due_at=body.due_at,
        priority=body.priority,
        related_project=body.related_project,
        related_entities=body.related_entities,
    )
    return {"open_loop": loop}


@router.post("/api/brain/open-loops/{loop_id}/complete")
def complete_open_loop(loop_id: str):
    done = get_brain().complete_open_loop(loop_id)
    if not done:
        raise HTTPException(404, "open loop not found")
    return {"open_loop": done}


@router.get("/api/brain/memories/{memory_id}")
def get_memory(memory_id: str):
    mem = get_brain().inspect_memory(memory_id)
    if not mem:
        raise HTTPException(404, "memory not found")
    return {"memory": mem}


@router.delete("/api/brain/memories/{memory_id}")
def delete_memory(memory_id: str):
    """Remove one memory the user picked out of a brain search.

    A hard delete, not a retraction. `store.delete(soft=True)` keeps the row and
    marks it `retracted`, which is right for a *superseded* fact — the brain's
    append-only history depends on it. It is wrong for this button: the user is
    pointing at one result and saying it should not be there, nothing supersedes
    it, and `store.count()` counts every row whatever its status — so a soft
    delete would leave the memory count unchanged and read as "nothing happened".

    Append-only is a rule about **canonical claims** in `brain.db`. This is the
    raw index, which `/api/brain/reset` and the enrichment pruner already treat
    as disposable.
    """
    if not get_brain().forget(memory_id, soft=False):
        raise HTTPException(404, "memory not found")
    return {"ok": True, "deleted": memory_id}


@router.get("/api/brain/memories/{memory_id}/explain")
def explain_memory(memory_id: str, q: str = ""):
    exp = get_brain().explain_memory(memory_id, query=q)
    if "error" in exp:
        raise HTTPException(404, exp["error"])
    return exp


@router.get("/api/brain/contradictions")
def get_contradictions():
    return {"contradictions": get_brain().detect_contradictions()}


class ResolveConflictIn(BaseModel):
    conflict: dict[str, Any]
    auto_supersede: bool = True


@router.post("/api/brain/contradictions/resolve")
def resolve_contradiction(body: ResolveConflictIn):
    return get_brain().resolve_contradiction(body.conflict, auto_supersede=body.auto_supersede)


@router.get("/api/brain/evaluate")
def evaluate_brain():
    return get_brain().evaluate_quality()


@router.get("/api/brain/export")
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


@router.post("/api/brain/import")
def brain_import(body: ImportIn):
    """Restore memories from an exported backup. Idempotent (dedup)."""
    return get_brain().import_data(body.model_dump())


# ── canonical Brain (curated, source-backed model of the user) ─────────────
def _canon():
    from ...brain.canonical import get_canonical
    return get_canonical()


class RememberIn(BaseModel):
    text: str
    provider: str | None = None
    model: str | None = None


@router.get("/api/brain/canonical")
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


@router.post("/api/brain/canonical/remember")
def canonical_remember(body: RememberIn):
    """Explicit 'remember this' → candidate → trust rules → canonical."""
    return _canon().remember(body.text, provider_name=body.provider,
                             model_name=body.model)


@router.get("/api/brain/canonical/review")
def canonical_review():
    return {"pending": _canon().pending()}


@router.post("/api/brain/canonical/review/{candidate_id}/approve")
def canonical_approve(candidate_id: str):
    return _canon().approve(candidate_id)


class RejectIn(BaseModel):
    reason: str = ""


@router.post("/api/brain/canonical/review/{candidate_id}/reject")
def canonical_reject(candidate_id: str, body: RejectIn):
    return _canon().reject(candidate_id, body.reason)


@router.post("/api/brain/canonical/maintain")
def canonical_maintain():
    """Freshness maintenance pass (mark aging/stale current claims)."""
    return _canon().maintain()


@router.post("/api/brain/canonical/export")
def canonical_export():
    """Regenerate the Markdown/JSON mirror under ~/Library/Lodestone/brain-export."""
    return _canon().export()


@router.get("/api/brain/canonical/evaluate")
def canonical_evaluate(k: int = 5):
    return _canon().evaluate(k=k)


# NOTE: keep this parametrized GET last — it must not shadow the specific
# /review and /evaluate GET routes above.
@router.get("/api/brain/canonical/{section}")
def canonical_section(section: str):
    cb = _canon()
    fn = {"about_you": cb.about_you, "people": cb.people,
          "work": cb.work, "timeline": cb.timeline}.get(section)
    if not fn:
        raise HTTPException(404, f"unknown section '{section}'")
    return {"section": section, "records": fn()}
