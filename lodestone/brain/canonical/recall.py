"""Canonical-first recall: build the CANONICAL FACTS block that leads the
context injected into every agent turn. Ordering is strict —
canonical facts win over raw memories unless the user asks to inspect sources.
"""
from __future__ import annotations

import re

from . import freshness
from .store import CanonicalStore, _norm


def _relevant(text: str, query_tokens: set[str]) -> int:
    toks = set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))
    return len(toks & query_tokens)


def build_block(store: CanonicalStore, query: str, *, max_claims: int = 8,
                max_events: int = 5, max_tokens: int = 900) -> dict:
    """Return {'block': str, 'claim_ids': [...], 'entity_ids': [...]}.

    Selects the current, high-signal canonical facts most relevant to the query.
    If the query is generic (few tokens), falls back to the freshest current
    facts so 'who am I / what am I working on' still gets a real answer.
    """
    qtokens = {t for t in re.findall(r"[a-z0-9]{3,}", (query or "").lower())}

    claims = store.current_claims()
    # score by lexical relevance to the query; entity name adds signal
    ent_names = {e["id"]: e["canonical_name"] for e in store.list_entities()}
    scored = []
    for c in claims:
        text = f"{ent_names.get(c.get('entity_id'), '')} {c['value']}"
        score = _relevant(text, qtokens)
        # always keep some baseline so generic queries still surface top facts
        recency = 0 if c.get("type") in freshness.TIME_SENSITIVE else 0
        scored.append((score, recency, c))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    picked = [c for s, _, c in scored if s > 0][:max_claims]
    if not picked:  # generic query → freshest current claims
        picked = [c for _, _, c in scored][:max_claims]

    lines: list[str] = []
    claim_ids: list[str] = []
    entity_ids: list[str] = []
    used = 0
    open_lines: list[str] = []
    for c in picked:
        f = freshness.compute(c)
        ent = ent_names.get(c.get("entity_id"))
        prefix = f"{ent}: " if ent else ""
        tag = ""
        if f == "stale":
            tag = " [STALE — reconfirm before relying on this]"
        elif f == "aging":
            tag = " [aging]"
        if c.get("confidence") == "inferred":
            tag += " (inferred)"
        line = f"- {prefix}{c['value']}{tag}"
        if c.get("state") == "open":
            open_lines.append(f"- OPEN/tentative: {prefix}{c['value']}")
            continue
        if used + len(line) > max_tokens * 4:
            break
        lines.append(line)
        used += len(line)
        claim_ids.append(c["id"])
        if c.get("entity_id"):
            entity_ids.append(c["entity_id"])

    # open commitments / deadlines
    task_lines = []
    for t in store.open_tasks()[:6]:
        due = f" (due {t['due_at']})" if t.get("due_at") else ""
        who = "" if t["owner"] == "user" else " [waiting on them]"
        task_lines.append(f"- {t['title']}{due}{who}")

    parts = []
    if lines:
        parts.append("Current facts:\n" + "\n".join(lines))
    if open_lines:
        parts.append("Unconfirmed / tentative:\n" + "\n".join(open_lines))
    if task_lines:
        parts.append("Open commitments:\n" + "\n".join(task_lines))

    block = ""
    if parts:
        block = "CANONICAL FACTS (curated, evidence-backed — trust these first):\n" \
                + "\n\n".join(parts)
    return {"block": block, "claim_ids": claim_ids, "entity_ids": entity_ids}
