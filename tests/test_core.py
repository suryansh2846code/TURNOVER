"""Smoke tests for the agent-first architecture — fully offline (mock + hash)."""
import os
import tempfile

os.environ.setdefault("LODESTONE_EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("LODESTONE_MODEL_PROVIDER", "mock")
os.environ["LODESTONE_HOME"] = tempfile.mkdtemp()

from lodestone.brain import Brain
from lodestone.core.store import MemoryStore
from lodestone.agents import run_turn, list_agents
from lodestone.models import get_provider, Message, Tool


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


def test_four_agents_exist():
    ids = {a.id for a in list_agents()}
    assert ids == {"inbox", "launch", "research", "personal"}


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
