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
    runtime_identity: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "reply": self.reply,
            "provider": self.provider,
            "model": self.model,
            "runtime_identity": self.runtime_identity,
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


PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "claude": "Anthropic",
    "anthropic": "Anthropic",
    "claude-code": "Claude Code",
    "gemini": "Google",
    "google": "Google",
    "cursor": "Cursor",
    "xai": "xAI",
    "grok": "xAI",
    "deepseek": "DeepSeek",
    "ollama": "Ollama",
    "openrouter": "OpenRouter",
    "subscription": "Subscription",
    "mock": "Mock",
}


def build_runtime_identity(agent: Agent, provider: Any) -> dict[str, Any]:
    provider_name = getattr(provider, "name", "unknown")
    provider_display = PROVIDER_DISPLAY_NAMES.get(provider_name.lower(), provider_name.title())
    model_name = getattr(provider, "model", "") or "default"

    harness = None
    if provider_name == "openai":
        try:
            from ..models.chatgpt_auth import get_chatgpt_access_token
            if not getattr(provider, "api_key", None) and get_chatgpt_access_token():
                harness = "Codex harness"
        except Exception:
            pass
    elif provider_name == "claude-code":
        harness = "Claude Code harness"
    elif provider_name == "cursor":
        harness = "Cursor session bridge"
    elif provider_name == "subscription":
        harness = "Subscription gateway"

    return {
        "application": "Lodestone",
        "agent_id": agent.id,
        "agent_name": agent.name,
        "agent_role": getattr(agent, "role", ""),
        "provider": provider_display,
        "provider_name": provider_name,
        "model": model_name,
        "harness": harness,
    }


def format_runtime_context_prompt(identity: dict[str, Any]) -> str:
    app = identity.get("application", "Lodestone")
    agent_name = identity.get("agent_name", "Assistant")
    role = identity.get("agent_role", "")
    provider = identity.get("provider", "Unknown")
    model = identity.get("model", "unknown")
    harness = identity.get("harness")

    lines = [
        "RUNTIME CONTEXT — AUTHORITATIVE",
        "",
        f"Application: {app}",
        f"Selected Agent: {agent_name}",
    ]
    if role:
        lines.append(f"Agent Role: {role}")
    lines.append(f"Provider: {provider}")
    lines.append(f"Model: {model}")
    if harness:
        lines.append(f"Harness: {harness}")

    role_desc = f"your {role} Agent" if role else f"the {agent_name} Agent"
    harness_suffix = f" through the {harness}" if harness else ""

    lines.extend([
        "",
        "The user selected this agent. The model/provider above are the actual runtime configuration for this turn.",
        "",
        'If asked "what model are you using?", "which AI are you using?", "what provider are you running on?", '
        'or similar questions, answer directly from this runtime context.',
        f"Example truthful answer: \"I'm {role_desc}, running on {provider}'s `{model}` model{harness_suffix}.\"",
        "- Do not claim the model is unknown if the Model field is populated.",
        "- Do not invent a different model.",
    ])
    return "\n".join(lines)


def run_turn(agent_id: str, user_text: str, *,
             provider_name: str | None = None,
             model_name: str | None = None) -> TurnResult:
    agent = get_agent(agent_id)
    settings = get_settings()
    p_name = (provider_name.strip() if provider_name else None) or agent.model_provider or settings.model_provider
    m_name = (model_name.strip() if model_name else None) or agent.model_name or settings.model_name
    provider = get_provider(p_name, m_name)
    identity = build_runtime_identity(agent, provider)
    # Fail fast with a helpful message if the chosen backend isn't usable.
    ready, why = provider.is_ready()
    if not ready:
        return TurnResult(
            agent_id=agent_id,
            reply=f"⚠️ The **{provider.name}** model isn't ready: {why}.\n\n"
                  "Pick another model in the Model dropdown, or fix the backend "
                  "(e.g. run `ollama serve`, or set the API key).",
            provider=provider.name, model=provider.model,
            runtime_identity=identity,
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

    runtime_prompt = format_runtime_context_prompt(identity)

    messages: list[Message] = [
        Message(role="system", content=runtime_prompt),
        Message(
            role="system",
            content=(
                agent.system_message()
                + f"\n\nRIGHT NOW it is {date_line}, {time_line}. This is the "
                  "authoritative current date — never state any other date as today. "
                  "Resolve 'today', 'tomorrow', 'this week' from this date."
            ),
        ),
    ]

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
                runtime_identity=identity,
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
    # (1) raw-memory capture (searchable evidence), (2) canonical curation so
    # the durable, versioned model of the user keeps up with the conversation.
    learned = _auto_learn(user_text, provider)
    if learned:
        trace.append(TraceStep(kind="tool_result", name="auto_learn",
                               result=f"learned {learned} new fact(s)"))
    try:
        from ..brain.canonical import get_canonical
        cres = get_canonical().learn_from_conversation(user_text, reply,
                                                        provider=provider)
        if cres.get("added") or cres.get("queued"):
            trace.append(TraceStep(
                kind="tool_result", name="brain_curate",
                result=f"{cres.get('added',0)} canonical, "
                       f"{cres.get('queued',0)} queued for review"))
    except Exception:
        pass  # curation must never break a chat turn
    return TurnResult(
        agent_id=agent.id, reply=reply, trace=trace,
        provider=provider.name, model=provider.model,
        runtime_identity=identity,
    )
