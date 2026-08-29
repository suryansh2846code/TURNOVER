"""Entity / relation extraction for the knowledge graph.

Two strategies:
  • LLM extraction (when a real model provider is configured) — asks the model
    for structured entities + facts. High quality.
  • Heuristic extraction (offline fallback) — conservative, precision-first:
    it only keeps candidates that *look* like real proper nouns and rejects the
    generic/programming words that pollute a knowledge graph. Better to miss a
    real entity than to fill the graph with junk like "Date" or "JSON".
"""
from __future__ import annotations

import json
import re

from ..models import Message, get_provider

# capitalized word / multi-word phrase (allows internal caps like WhatsApp)
_CAP = re.compile(r"\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,3})\b")
_ARTICLE = re.compile(r"^(the|a|an|my|your|our|their|his|her|its)\s+", re.I)
_INTERNAL_CAP = re.compile(r"[a-z][A-Z]")   # e.g. WhatsApp, SokoArena, OpenRouter
_HAS_DIGIT = re.compile(r"\d")

# Generic English + programming words that are frequently Title-cased (sentence
# starts, code identifiers) but are NOT meaningful entities. Precision matters.
_NOISE = {
    # generic english
    "the", "this", "that", "then", "there", "these", "those", "here", "when",
    "where", "what", "which", "while", "with", "your", "you", "they", "them",
    "and", "but", "for", "not", "are", "was", "were", "will", "would", "could",
    "should", "have", "has", "had", "been", "into", "from", "also", "just",
    "some", "more", "most", "other", "such", "than", "then", "them", "each",
    "every", "both", "either", "date", "time", "day", "week", "month", "year",
    "today", "tomorrow", "yesterday", "now", "next", "last", "first", "second",
    "outfit", "promise", "example", "note", "notes", "step", "steps", "part",
    "thing", "things", "way", "ways", "case", "cases", "point", "item", "list",
    "name", "title", "value", "order", "group", "total", "count", "detail",
    "overview", "summary", "section", "reason", "goal", "goals", "idea",
    # programming / tech generic
    "json", "html", "css", "http", "https", "url", "uri", "api", "apis", "uuid",
    "id", "ids", "sql", "cli", "sdk", "npm", "env", "todo", "fixme", "readme",
    "true", "false", "null", "none", "void", "function", "class", "const", "let",
    "var", "import", "export", "async", "await", "return", "error", "errors",
    "response", "request", "result", "results", "object", "objects", "string",
    "number", "boolean", "array", "arrays", "map", "set", "type", "types",
    "data", "file", "files", "path", "paths", "user", "users", "page", "pages",
    "table", "index", "event", "events", "state", "props", "style", "styles",
    "color", "image", "images", "button", "input", "output", "config", "server",
    "client", "model", "models", "token", "tokens", "query", "field", "fields",
    "status", "message", "messages", "content", "header", "footer", "main",
    "test", "tests", "build", "start", "stop", "run", "add", "get", "post",
    "put", "delete", "update", "create", "new", "old", "adr", "app", "apps",
    "code", "line", "lines", "block", "node", "key", "keys", "props", "hook",
    # document-structure / ADR / template headings
    "accepted", "rejected", "proposed", "deprecated", "superseded", "negative",
    "positive", "neutral", "alternatives", "consequences", "decision",
    "decisions", "context", "owner", "verified", "unverified", "background",
    "motivation", "scope", "conclusion", "introduction", "appendix",
    "references", "prerequisites", "requirements", "approach", "solution",
    "problem", "options", "tradeoffs", "pros", "cons", "risks", "benefits",
    "changelog", "roadmap", "milestone", "abstract", "objective", "objectives",
    "status", "priority", "severity", "category", "version", "author", "date",
    # weekdays / http verbs / misc
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "patch", "head", "options", "trace", "connect",
}


def is_good_entity(name: str) -> bool:
    """Precision-first filter: does this look like a real named entity?"""
    name = _ARTICLE.sub("", name).strip()
    if not name:
        return False
    words = name.split()
    # multi-word Title-case phrases are almost always real (Cloudflare Workers)
    if len(words) >= 2:
        # but reject if every word is noise
        return not all(w.lower() in _NOISE for w in words)
    # single word: must be distinctive and not generic
    w = words[0]
    if w.lower() in _NOISE:
        return False
    if _INTERNAL_CAP.search(w) or _HAS_DIGIT.search(w):
        return True                     # WhatsApp, SokoArena, S3, GPT4
    if w.isupper():
        return len(w) >= 3 and w.lower() not in _NOISE  # real acronyms: NASA, SIH
    return len(w) >= 4                   # plain Title word, e.g. Groq, Notion


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()   # collapse line breaks/spaces
    return _ARTICLE.sub("", name).strip()


def extract_heuristic(text: str) -> dict:
    entities: dict[str, dict] = {}
    for m in _CAP.finditer(text):
        name = _clean_name(m.group(1))
        if not is_good_entity(name):
            continue
        entities.setdefault(name, {"name": name, "type": "thing", "summary": ""})

    facts = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        sent = sent.strip()
        if len(sent) < 25:              # skip fragments/noise
            continue
        names = [n for n in entities if n in sent]
        if names:
            facts.append({
                "subject": names[0], "predicate": "mentioned_in",
                "object": None, "fact": sent[:240],
            })
    return {"entities": list(entities.values())[:10], "facts": facts[:8]}


_SYS = (
    "Extract a small knowledge graph from the text. Return STRICT JSON: "
    '{"entities":[{"name":str,"type":"person|project|org|tool|place|topic|thing",'
    '"summary":str}],"facts":[{"subject":str,"predicate":str,"object":str|null,'
    '"fact":str}]}. Only include salient, durable, specific entities (real names '
    "of people, projects, tools, orgs, places). NEVER include generic words like "
    "Date, JSON, Error, Function, Response. No prose."
)


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
            # still run the quality filter over LLM output as a safety net
            data["entities"] = [
                e for e in data["entities"]
                if e.get("name") and is_good_entity(e["name"])
            ]
            return data
    except Exception:
        return None
    return None


def extract(text: str, provider_name: str | None = None) -> dict:
    return extract_llm(text, provider_name) or extract_heuristic(text)
