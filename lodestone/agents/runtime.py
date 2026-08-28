"""Agent runtime: the model + tool-use loop that makes an agent *do* things."""
from __future__ import annotations

import json
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
    for row in mem.history(agent.id, limit=20):
        # replay only clean user/assistant turns for context (skip tool plumbing)
        if row["role"] in ("user", "assistant") and row["content"]:
            msgs.append(Message(role=row["role"], content=row["content"]))
    return msgs


def run_turn(agent_id: str, user_text: str, *,
             provider_name: str | None = None) -> TurnResult:
    agent = get_agent(agent_id)
    settings = get_settings()
    provider = get_provider(
        provider_name or agent.model_provider or settings.model_provider,
        agent.model_name or settings.model_name,
    )
    mem = AgentMemory()
    tools = build_tools(agent.tools)

    messages: list[Message] = [Message(role="system", content=agent.system_message())]

    # Auto-recall: inject the relevant slice of the brain up front so the agent
    # *already knows the user* regardless of whether the (possibly small) model
    # decides to call search_brain. Tools remain for going deeper / live data.
    trace: list[TraceStep] = []
    recalled = get_brain().recall(user_text, limit=6)
    if recalled["context"]:
        messages.append(Message(role="system", content=recalled["context"]))
        trace.append(TraceStep(
            kind="tool_result", name="auto_recall",
            result=f"{len(recalled['memory_hits'])} memories, "
                   f"{len(recalled['entities'])} entities",
        ))

    messages += _load_history(mem, agent)
    messages.append(Message(role="user", content=user_text))
    mem.append(agent.id, "user", user_text)
    reply = ""
    for _ in range(MAX_STEPS):
        result = provider.chat(messages, tools=tools, temperature=0.4)
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
    return TurnResult(
        agent_id=agent.id, reply=reply, trace=trace,
        provider=provider.name, model=provider.model,
    )
