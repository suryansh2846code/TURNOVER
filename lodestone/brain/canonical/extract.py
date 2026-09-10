"""Candidate extraction — turn cleaned text into proposed canonical records.

Two strategies (same philosophy as the graph extractor):
  • LLM extraction when a real provider is available — structured, precise.
  • Heuristic fallback — conservative self-disclosure capture so the Brain still
    grows offline.

Extraction NEVER writes to canonical truth. It only proposes Candidates; the
curator (curate.py) applies the trust rules and the review queue.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Tentative language → an `open` claim/event, never a current fact.
TENTATIVE = re.compile(
    r"\b(maybe|might|may|could|considering|thinking about|thinking of|possibly|"
    r"perhaps|tentativel?y?|planning to|hope to|hoping to|not sure|probably|"
    r"leaning towards?|we'll see|explore|exploring|potential(?:ly)?|idea to)\b", re.I)

# First-person durable self-disclosure → a CONFIRMED about_you claim.
_DISCLOSURE = re.compile(
    r"\b(i am|i'm|my name is|i work|i'm working|i live|i'm based|i prefer|i like|"
    r"i love|i hate|i use|i build|i'm building|i want|i need|i'm learning|"
    r"i usually|i always|i own|i run|i lead|i founded|remember that|note that|"
    r"i'm a|i am a)\b", re.I)

# Map disclosure verbs → (section, claim type).
_TYPE_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bi (prefer|like|love|hate|use|enjoy)\b", re.I), "about_you", "preference"),
    (re.compile(r"\bi(?:'m| am) (building|working on|shipping|launching)\b", re.I), "work", "project_status"),
    (re.compile(r"\bi (want|need|hope|plan|aim|goal)\b", re.I), "about_you", "goal"),
    (re.compile(r"\bi(?:'m| am) (a |an )?(founder|engineer|developer|designer|student|ceo|pm|manager)\b", re.I), "about_you", "role"),
    (re.compile(r"\bi (live|'m based|work) (in|at|from)\b", re.I), "about_you", "location"),
    (re.compile(r"\bi (decided|chose|going with|picked)\b", re.I), "work", "decision"),
]


def classify(sentence: str) -> tuple[str, str]:
    for pat, section, typ in _TYPE_RULES:
        if pat.search(sentence):
            return section, typ
    return "about_you", "preference"


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?\n])\s+", text) if s.strip()]


def heuristic_candidates(text: str, *, actor: str = "user") -> list[dict[str, Any]]:
    """Offline fallback: capture the user's own durable self-disclosures.

    Only mines FIRST-PERSON user statements — never invents facts about other
    people (that needs the LLM). Every result is a confirmed about_you/work
    claim unless the sentence is tentative."""
    if actor != "user":
        return []
    out: list[dict[str, Any]] = []
    for sent in _split_sentences(text):
        if not _DISCLOSURE.search(sent):
            continue
        section, typ = classify(sent)
        out.append({
            "kind": "claim", "section": section, "type": typ,
            "value": sent.rstrip(".!?"),
            "confidence": "confirmed",
            "tentative": bool(TENTATIVE.search(sent)),
            "entity": None,
            "evidence_excerpt": sent,
        })
    return out[:6]


_LLM_SYS = (
    "You extract a small, durable, source-backed model of a user from text "
    "(an email, a chat message, a document). Return STRICT JSON:\n"
    '{"candidates": [ ... ]}\n'
    "Each candidate is ONE of:\n"
    '  claim:  {"kind":"claim","section":"about_you|people|work","type":'
    '"preference|goal|role|project_status|decision|risk|next_step|relationship",'
    '"value":"<concise third-person statement>","entity":{"type":"person|project|'
    'organization","name":"...","identifiers":[{"kind":"email|github_login|alias",'
    '"value":"..."}]} or null,"confidence":"confirmed|inferred","tentative":true|false,'
    '"evidence_excerpt":"<short quote>"}\n'
    '  event:  {"kind":"event","event_type":"interaction|decision|commitment|'
    'milestone|change","occurred_at":"YYYY-MM-DD","summary":"...","entity":{...} or null,'
    '"evidence_excerpt":"..."}\n'
    '  task:   {"kind":"task","title":"...","owner":"user|external_person",'
    '"due_at":"YYYY-MM-DD or null","entity":{...} or null,"evidence_excerpt":"..."}\n\n'
    "RULES: Only durable, decision-relevant facts — never newsletters, receipts, "
    "OTPs, or small talk. Tentative language (maybe/considering/might) → "
    '"tentative":true. Mark "confirmed" only for explicit, stated fact; use '
    '"inferred" for anything you deduced. Prefer stable identifiers (email, '
    "handle) on entities. Empty list if nothing durable. Output JSON only."
)


def llm_candidates(text: str, provider, *, event_date: str | None = None) -> list[dict[str, Any]]:
    from ...models import Message
    ctx = f"(source date: {event_date})\n" if event_date else ""
    res = provider.chat(
        [Message(role="system", content=_LLM_SYS),
         Message(role="user", content=ctx + text[:6000])],
        temperature=0, max_tokens=900)
    raw = res.text
    try:
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw)
    except Exception:
        return []
    cands = data.get("candidates", [])
    # normalize tentative flag from language even if the model missed it
    for c in cands:
        blob = " ".join(str(c.get(k, "")) for k in ("value", "summary", "title"))
        if TENTATIVE.search(blob):
            c["tentative"] = True
        c.setdefault("confidence", "inferred")
        c.setdefault("tentative", False)
    return [c for c in cands if isinstance(c, dict) and c.get("kind")]


def extract_candidates(text: str, provider=None, *, actor: str = "user",
                       event_date: str | None = None) -> list[dict[str, Any]]:
    """Best-available extraction. Uses the LLM when ready, else heuristics."""
    if provider is not None:
        try:
            ready, _ = provider.is_ready()
            if provider.name != "mock" and ready:
                cands = llm_candidates(text, provider, event_date=event_date)
                if cands:
                    return cands
        except Exception:
            pass
    return heuristic_candidates(text, actor=actor)
