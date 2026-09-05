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

# Bump when extraction logic changes → auto-migration rebuilds the graph for all
# users on next startup (no manual rebuild-graph).
EXTRACTOR_VERSION = "4"

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
    # instructional / exam / document verbs & headings (from docs & PDFs)
    "explain", "write", "answer", "answers", "discuss", "define", "describe",
    "list", "state", "prove", "derive", "calculate", "find", "show", "solve",
    "solved", "attempt", "marks", "mark", "unit", "ans", "question", "questions",
    "chapter", "topic", "topics", "paper", "exam", "assignment", "syllabus",
    "human", "body", "right", "left", "self", "thus", "hence", "given", "let",
    "consider", "assume", "suppose", "hello", "hi", "thanks", "thank", "regards",
    "dear", "best", "great", "good", "welcome", "please", "kindly", "yours",
    "figure", "table", "diagram", "example", "solution", "problem", "theorem",
    "definition", "introduction", "conclusion", "abstract", "values", "value",
    # email CTAs / UI actions
    "apply", "join", "view", "learn", "check", "click", "register", "download",
    "install", "subscribe", "follow", "share", "save", "open", "close", "read",
    "watch", "listen", "buy", "shop", "sign", "login", "logout", "signup",
    "enroll", "explore", "discover", "browse", "continue", "confirm", "verify",
    "activate", "upgrade", "renew", "book", "schedule", "rsvp", "attend",
    "location", "venue", "online", "offline", "virtual", "webinar", "session",
    # months / timezones / time
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "gmt", "utc", "pst", "est", "ist", "cst", "edt", "pdt",
    # email / html boilerplate
    "subject", "doctype", "arial", "helvetica", "verdana", "sans", "serif",
    "mailto", "unsubscribe", "viewport", "charset", "span", "div", "href",
    "email", "inbox", "reply", "forward", "cc", "bcc", "sender", "recipient",
    "newsletter", "webkit", "margin", "padding", "font", "img", "src", "alt",
}


def _looks_like_token(w: str) -> bool:
    """Reject random ids / base64 / hashes (e.g. ACUX6DMKR70acllgpm5Sd0…): long
    strings with few vowels or many digits are not real entity names."""
    if len(w) < 16:
        return False
    letters = sum(c.isalpha() for c in w)
    vowels = sum(c in "aeiouAEIOU" for c in w)
    digits = sum(c.isdigit() for c in w)
    if digits >= 4:
        return True
    return bool(letters) and (vowels / letters) < 0.30


def is_good_entity(name: str) -> bool:
    """Precision-first filter: does this look like a real named entity?"""
    name = _clean_name(name)
    if not name or len(name) > 45:
        return False
    words = name.split()
    if len(words) == 1 and _looks_like_token(words[0]):
        return False
    # multi-word Title-case phrases are almost always real (Cloudflare Workers)
    if len(words) >= 2:
        # but reject if every word is noise
        return not all(w.lower() in _NOISE for w in words)
    # single word: must be distinctive and not generic
    w = words[0]
    if w.lower() in _NOISE:
        return False
    if re.fullmatch(r"[A-Za-z]\d{1,2}", w):
        return False                    # L2, L6, S3, v2 — cache-level / version noise
    if _INTERNAL_CAP.search(w):
        return True                     # WhatsApp, SokoArena, OpenRouter
    if _HAS_DIGIT.search(w):
        return len(w) >= 4              # GPT4, H100 — but not L6/v2 (caught above)
    if w.isupper():
        return len(w) >= 3 and w.lower() not in _NOISE  # real acronyms: NASA, SIH
    return len(w) >= 4                   # plain Title word, e.g. Groq, Notion


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()   # collapse line breaks/spaces
    name = _ARTICLE.sub("", name).strip()
    # drop trailing/leading connector words the capture regex swept in, so
    # "Product Management Meetup When" → "Product Management Meetup",
    # "IDfy Mumbai With" → "IDfy Mumbai".
    words = name.split()
    while words and words[-1].lower() in _NOISE:
        words.pop()
    while words and words[0].lower() in _NOISE:
        words.pop(0)
    return " ".join(words)


# Curated hints so the offline heuristic can type entities instead of "thing".
_KNOWN_TOOLS = {
    "cloudflare", "workers", "groq", "typescript", "javascript", "python",
    "react", "next.js", "nextjs", "node", "sqlite", "postgres", "d1", "kv", "r2",
    "vectorize", "wrangler", "oauth", "jwt", "docker", "kubernetes", "redis",
    "openai", "anthropic", "claude", "gpt", "gemini", "ollama", "llama", "qwen",
    "langchain", "fastapi", "flask", "django", "vite", "tailwind", "supabase",
    "firebase", "vercel", "netlify", "stripe", "razorpay", "twilio", "resend",
    "notion", "linear", "slack", "gmail", "sheets", "drive", "webhook", "api",
    "sdk", "mcp", "llm", "rag", "crm", "ui", "cli",
}
_ORG_HINTS = {"inc", "llc", "ltd", "corp", "labs", "technologies", "agency",
              "meta", "google", "microsoft", "amazon", "apple", "openai",
              "anthropic", "cloudflare", "algorand"}
_PERSON_HINT = re.compile(r"^[A-Z][a-z]+ [A-Z][a-z]+$")   # First Last
# common Title-cased words that look like "First Last" but aren't people
# (so "Building High", "Data Platform", "Product Meeting" aren't tagged person)
_NOT_NAME = {
    "building", "high", "low", "data", "platform", "platforms", "performance",
    "management", "product", "meetup", "meeting", "project", "team", "report",
    "plan", "review", "update", "design", "system", "service", "feature",
    "release", "launch", "growth", "sales", "market", "budget", "revenue",
    "customer", "client", "partner", "vendor", "invoice", "payment", "order",
    "ticket", "issue", "task", "note", "email", "message", "call", "event",
    "deadline", "goal", "target", "metric", "quarter", "sprint", "backlog",
    "morning", "evening", "night", "happy", "good", "great", "best", "new",
}


def guess_type(name: str) -> str:
    low = name.lower()
    words = low.split()
    if any(w in _KNOWN_TOOLS for w in words):
        return "tool"
    if any(w in _ORG_HINTS for w in words):
        return "org"
    if _PERSON_HINT.match(name) and not any(w in _NOT_NAME for w in words):
        return "person"
    if len(words) >= 2 and name[0].isupper():
        return "project"      # multi-word proper noun, not a known tool/org
    return "thing"


def extract_heuristic(text: str) -> dict:
    entities: dict[str, dict] = {}
    for m in _CAP.finditer(text):
        name = _clean_name(m.group(1))
        if not is_good_entity(name):
            continue
        entities.setdefault(name, {"name": name, "type": guess_type(name), "summary": ""})

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


# ── general text cleaning (works for ANY connector's raw content) ───────────
_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_ENT = re.compile(r"&[a-z#0-9]+;", re.I)
_URL = re.compile(r"https?://\S+|www\.\S+")
_QUOTED = re.compile(r"^\s*>.*$", re.M)                       # quoted email replies
_LONG_TOKEN = re.compile(r"\S{40,}")                          # base64 / hashes / ids
_BOILER = re.compile(r"(?im)^\s*(unsubscribe|view (this|it) in|sent from my|"
                     r"do not reply|this (e-?mail|message)|confidential|"
                     r"©|all rights reserved|privacy policy).*$")
_WS = re.compile(r"[ \t ]+")
_MULTINL = re.compile(r"\n{3,}")


def clean_for_extraction(text: str) -> str:
    """Strip markup, quoted replies, URLs, boilerplate and encoded blobs so the
    extractor sees human language, whatever connector the text came from."""
    t = text or ""
    t = _HTML_TAG.sub(" ", t)
    t = _HTML_ENT.sub(" ", t)
    t = _QUOTED.sub("", t)
    t = _BOILER.sub("", t)
    t = _URL.sub(" ", t)
    t = _LONG_TOKEN.sub(" ", t)
    t = _WS.sub(" ", t)
    t = _MULTINL.sub("\n\n", t)
    return t.strip()


def is_graphable(text: str) -> bool:
    """General signal test: is there enough clean human-language content here to
    pull entities from? (Rejects tiny snippets and data/code dumps.)"""
    t = (text or "").strip()
    if len(t) < 40:
        return False
    letters = sum(c.isalpha() for c in t)
    return letters >= 30 and letters / len(t) > 0.45
