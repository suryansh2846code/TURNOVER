"""Agent runtime: the model + tool-use loop that makes an agent *do* things."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..brain import get_brain
from ..config import get_settings
from ..models import Message, get_provider
from .agent import Agent, AgentMemory
from .presets import get_agent
from .tools import build_tools, run_tool

MAX_STEPS = 5


@dataclass
class TraceStep:
    kind: str                       # "tool_call" | "tool_result"
    name: str = ""
    arguments: dict = field(default_factory=dict)
    result: str = ""


@dataclass
class TurnResult:
    agent_id: str
    reply: str
    trace: list[TraceStep] = field(default_factory=list)
    provider: str = ""
    model: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "reply": self.reply,
            "provider": self.provider,
            "model": self.model,
            "trace": [
                {"kind": s.kind, "name": s.name,
                 "arguments": s.arguments, "result": s.result}
                for s in self.trace
            ],
        }


def _load_history(mem: AgentMemory, agent: Agent) -> list[Message]:
    msgs: list[Message] = []
    # keep a short window — long histories confuse small models and let stale
    # turns bleed into unrelated answers. Facts persist in the brain anyway.
    for row in mem.history(agent.id, limit=6):
        # replay only clean user/assistant turns for context (skip tool plumbing)
        if row["role"] in ("user", "assistant") and row["content"]:
            msgs.append(Message(role=row["role"], content=row["content"]))
    return msgs


_LEARN_SYS = (
    "From the user's message, extract ONLY durable facts they revealed about "
    "themselves, their work, people, preferences, or plans — things worth "
    "remembering long-term. Ignore questions, commands, and small talk. "
    'Return STRICT JSON: {"facts": ["...", "..."]}. Empty list if nothing durable. '
    "Write each fact as a standalone third-person statement (e.g. 'The user "
    "prefers X')."
)

# first-person cues that suggest the user is disclosing something durable
_DISCLOSURE = re.compile(
    r"\b(i am|i'm|my |i work|i live|i prefer|i like|i hate|i use|i build|"
    r"i'm building|i want|i need|remember that|i usually|i always|i own)\b",
    re.I,
)


def _auto_learn(user_text: str, provider) -> int:
    text = user_text.strip()
    # cheap gate: skip pure questions / anything with no self-disclosure
    if text.endswith("?") and not _DISCLOSURE.search(text):
        return 0
    if not _DISCLOSURE.search(text):
        return 0

    facts: list[str] = []
    ready, _ = provider.is_ready()
    if provider.name != "mock" and ready:
        try:
            res = provider.chat(
                [Message(role="system", content=_LEARN_SYS),
                 Message(role="user", content=text[:1500])],
                temperature=0, max_tokens=300,
            )
            raw = res.text
            raw = raw[raw.find("{"): raw.rfind("}") + 1]
            facts = [f for f in json.loads(raw).get("facts", []) if f.strip()]
        except Exception:
            facts = []
    if not facts:
        # heuristic fallback: store the disclosing sentence itself
        facts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text)
                 if _DISCLOSURE.search(s)][:3]

    brain = get_brain()
    stored = 0
    for fact in facts[:5]:
        if brain.ingest(fact, source="agent", kind="fact", title="learned")["memories"]:
            stored += 1
    return stored


def run_turn(agent_id: str, user_text: str, *,
             provider_name: str | None = None,
             model_name: str | None = None) -> TurnResult:
    agent = get_agent(agent_id)
    settings = get_settings()
    provider = get_provider(
        provider_name or agent.model_provider or settings.model_provider,
        model_name or agent.model_name or settings.model_name,
    )
    # Fail fast with a helpful message if the chosen backend isn't usable.
    ready, why = provider.is_ready()
    if not ready:
        return TurnResult(
            agent_id=agent_id,
            reply=f"⚠️ The **{provider.name}** model isn't ready: {why}.\n\n"
                  "Pick another model in the Model dropdown, or fix the backend "
                  "(e.g. run `ollama serve`, or set the API key).",
            provider=provider.name, model=provider.model,
        )
    mem = AgentMemory()
    tools = build_tools(agent.tools)

    # Ground the agent in the present. LLMs have no clock, so without this they
    # hallucinate the date. Small models ignore mid-context system notes, so we
    # (a) state it in the system prompt AND (b) prepend it to the model-facing
    # user turn — right next to the question, where even a 3B model can't miss it.
    from datetime import datetime
    now = datetime.now().astimezone()
    date_line = f"{now:%A, %B %d, %Y}"
    time_line = f"{now:%-I:%M %p} {now:%Z}"

    messages: list[Message] = [Message(
        role="system",
        content=(
            agent.system_message()
            + f"\n\nRIGHT NOW it is {date_line}, {time_line}. This is the "
              "authoritative current date — never state any other date as today. "
              "Resolve 'today', 'tomorrow', 'this week' from this date."
        ),
    )]

    # Auto-recall: inject the relevant slice of the brain up front so the agent
    # *already knows the user* regardless of whether the (possibly small) model
    # decides to call search_brain. Tools remain for going deeper / live data.
    trace: list[TraceStep] = []
    recalled = get_brain().recall(
        user_text, limit=10, prefer=agent.recall_sources or None)
    if recalled["context"]:
        messages.append(Message(role="system", content=recalled["context"]))
        trace.append(TraceStep(
            kind="tool_result", name="auto_recall",
            result=f"{len(recalled['memory_hits'])} memories, "
                   f"{len(recalled['entities'])} entities",
        ))

    # Ground task-capable agents in the ACTUAL current tasks (authoritative),
    # so they never invent or regurgitate stale tasks from chat history.
    if "list_tasks" in agent.tools:
        from ..tasks import get_tasks
        open_tasks = get_tasks().list()
        if open_tasks:
            lines = [f"- {t['title']}" + (f" (due {t['due']})" if t["due"] else "")
                     for t in open_tasks[:20]]
            messages.append(Message(
                role="system",
                content=("The user's CURRENT open tasks (this is the authoritative "
                         "list — use it; never invent tasks not shown here):\n"
                         + "\n".join(lines)),
            ))
        else:
            messages.append(Message(
                role="system",
                content="The user currently has NO open tasks. Do not claim otherwise.",
            ))

    messages += _load_history(mem, agent)
    # model sees the date adjacent to the question; stored memory stays clean
    messages.append(Message(
        role="user", content=f"[Today is {date_line}.]\n{user_text}"))
    mem.append(agent.id, "user", user_text)
    reply = ""
    for _ in range(MAX_STEPS):
        # low temperature → more reliable instruction-following & tool use
        try:
            result = provider.chat(messages, tools=tools, temperature=0.15)
        except Exception as exc:
            hint = ""
            if provider.name == "ollama":
                hint = " Is Ollama running? Start it with `ollama serve`."
            elif provider.name in ("anthropic", "openai", "openrouter"):
                hint = " Check the API key and your connection."
            return TurnResult(
                agent_id=agent_id,
                reply=f"⚠️ The **{provider.name}** model failed: "
                      f"{str(exc)[:200]}.{hint}",
                trace=trace, provider=provider.name, model=provider.model,
            )
        if result.wants_tools:
            messages.append(Message(
                role="assistant", content=result.text, tool_calls=result.tool_calls,
            ))
            for call in result.tool_calls:
                trace.append(TraceStep(
                    kind="tool_call", name=call.name, arguments=call.arguments))
                output = run_tool(call.name, call.arguments)
                trace.append(TraceStep(kind="tool_result", name=call.name,
                                       result=output))
                messages.append(Message(
                    role="tool", content=output, tool_call_id=call.id,
                    name=call.name,
                ))
            continue
        reply = result.text
        break
    else:
        reply = reply or "(stopped after max tool steps)"

    mem.append(agent.id, "assistant", reply,
               tool_json=json.dumps([s.name for s in trace if s.kind == "tool_call"]))

    # Auto-learn: quietly capture durable facts the user revealed this turn, so
    # simply talking to an agent grows the brain — no manual "add fact" step.
    learned = _auto_learn(user_text, provider)
    if learned:
        trace.append(TraceStep(kind="tool_result", name="auto_learn",
                               result=f"learned {learned} new fact(s)"))
    return TurnResult(
        agent_id=agent.id, reply=reply, trace=trace,
        provider=provider.name, model=provider.model,
    )
