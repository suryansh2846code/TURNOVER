"""Entity / relation extraction for the knowledge graph.

Two strategies:
  • LLM extraction (when a real model provider is configured) — asks the model
    for structured entities + facts.
  • Heuristic extraction (offline fallback) — capitalized noun phrases as
    entities plus simple subject–verb patterns as facts.
The brain uses the LLM path when available and always falls back cleanly, so
graph-building works with zero API keys.
"""
from __future__ import annotations

import json
import re

from ..models import Message, get_provider

_CAP = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,3})\b")
_STOP = {"The", "This", "That", "It", "I", "We", "You", "They", "A", "An", "My"}

_SYS = (
    "Extract a small knowledge graph from the text. Return STRICT JSON: "
    '{"entities":[{"name":str,"type":"person|project|org|tool|place|topic|thing",'
    '"summary":str}],"facts":[{"subject":str,"predicate":str,"object":str|null,'
    '"fact":str}]}. Only include salient, durable entities. No prose.'
)


def extract_heuristic(text: str) -> dict:
    entities: dict[str, dict] = {}
    for m in _CAP.finditer(text):
        name = m.group(1).strip()
        if name in _STOP or len(name) < 3:
            continue
        entities.setdefault(name, {"name": name, "type": "thing", "summary": ""})
    facts = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        names = [n for n in entities if n in sent]
        if names:
            facts.append({
                "subject": names[0], "predicate": "mentioned_in",
                "object": None, "fact": sent.strip()[:240],
            })
    return {"entities": list(entities.values())[:12], "facts": facts[:12]}


def extract_llm(text: str, provider_name: str | None = None) -> dict | None:
    provider = get_provider(provider_name)
    if provider.name == "mock":
        return None
    ready, _ = provider.is_ready()
    if not ready:
        return None
    try:
        res = provider.chat(
            [Message(role="system", content=_SYS),
             Message(role="user", content=text[:4000])],
            temperature=0, max_tokens=800,
        )
        raw = res.text.strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw)
        if "entities" in data:
            return data
    except Exception:
        return None
    return None


def extract(text: str, provider_name: str | None = None) -> dict:
    return extract_llm(text, provider_name) or extract_heuristic(text)
