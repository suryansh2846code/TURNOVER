"""Smoke tests for the agent-first architecture — fully offline (mock + hash)."""
import os
import tempfile

os.environ.setdefault("LODESTONE_EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("LODESTONE_MODEL_PROVIDER", "mock")
os.environ["LODESTONE_HOME"] = tempfile.mkdtemp()

from lodestone.agents import list_agents, run_turn
from lodestone.brain import Brain
from lodestone.core.store import MemoryStore
from lodestone.models import Message, Tool, get_provider


def _brain():
    store = MemoryStore(db_path=tempfile.mktemp(suffix=".db"))
    return Brain(store=store)


def test_ingest_builds_graph():
    b = _brain()
    out = b.ingest("Suryansh builds the WhatsApp Agent on Cloudflare Workers and Groq.")
    assert out["memories"] == 1
    assert out["entities"] >= 1
    stats = b.stats()
    assert stats["graph"]["entities"] >= 1


def test_brain_recall_fuses_graph_and_memories():
    b = _brain()
    b.ingest("SokoArena is an Algorand x402 challenge where agents solve Sokoban.",
             title="sokoarena")
    res = b.recall("what is sokoarena?")
    assert res["context"]
    assert "sokoarena" in res["context"].lower() or res["memory_hits"]


def test_nothing_is_pre_added_and_the_library_is_where_a_team_comes_from():
    """This asserted four shipped agents, then a smaller starter set, and now
    none — because an agent nobody picked is an agent nobody opens, and four
    strangers in a sidebar made the library look like a page of spares.

    A fresh install is not empty: onboarding builds the user their own lead
    agent. What must be true is that no *template* arrives unasked.
    """
    from lodestone.agents.library import BY_ID, DEFAULT_ROSTER

    assert DEFAULT_ROSTER == [], "a template is still being pre-added"
    assert len(BY_ID) >= 8, "the library people choose from is thin"
    assert not ({a.id for a in list_agents()} & set(BY_ID)), (
        "a library template is in the roster without anybody adding it")


def test_agent_tool_loop_uses_brain():
    b = _brain()
    b.ingest("The user prefers TypeScript and Cloudflare Workers.", title="prefs")
    res = run_turn("research", "what languages do I prefer?")
    called = [s.name for s in res.trace if s.kind == "tool_call"]
    assert "search_brain" in called          # agent reached into the brain
    assert res.reply                          # and produced an answer
    assert res.provider == "mock"


def test_provider_registry():
    p = get_provider("mock")
    r = p.chat([Message(role="user", content="hi")],
               tools=[Tool(name="search_brain", description="x", parameters={})])
    # with a search_brain tool available, mock chooses to call it first
    assert r.wants_tools


def test_task_store_due_parsing():
    import tempfile
    from datetime import date, timedelta

    from lodestone.tasks import TaskStore
    ts = TaskStore(db_path=tempfile.mktemp(suffix=".db"))
    t = ts.add("finish the launch page tomorrow")
    assert t["title"] == "finish the launch page"          # date phrase stripped
    assert t["due"] == (date.today() + timedelta(days=1)).isoformat()
    ts.add("call supplier today")
    assert len(ts.list(when="today")) == 1
    assert ts.stats()["today"] == 1
    ts.complete("call supplier")
    assert ts.stats()["today"] == 0
