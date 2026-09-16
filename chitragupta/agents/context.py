"""What the agent remembers of the conversation.

The old window was six messages — three exchanges — with a comment explaining
that long histories confuse small models and let stale turns bleed into
unrelated answers. Both halves of that are true. The conclusion drawn from them
was not: the fix for "too much history" is to *compress* the old part, not to
delete it. An assistant billed as a chief of staff that cannot remember what you
said four messages ago is not one.

So recent turns stay word-for-word, and everything older becomes a short running
summary carried as a system note. The summary is written once and then extended
— only the slice that has newly aged out is folded in — so a long conversation
does not re-summarise itself from scratch on every message.

Which writer is used follows the effort setting. At Low it is the offline
heuristic, because a small local model should not spend a call summarising
before it has even read the question. At Medium and High the model writes it,
because a real summary keeps intent and decisions that a heuristic drops.
"""
from __future__ import annotations

import json

from ..log import get_logger, suppressed
from ..models import Message
from .agent import Agent, AgentMemory
from .effort import Effort

log = get_logger(__name__)

#: Below this there is nothing worth compressing — the verbatim window already
#: holds the whole conversation.
MIN_TO_COMPACT = 4

#: Keeps the note small enough to stay cheap on every subsequent turn.
MAX_SUMMARY_CHARS = 1500

#: How much of one tool's answer is kept for later turns. Enough to recognise
#: what was found and answer "what was that third one again?"; short enough that
#: a handful of them do not crowd out the conversation.
MAX_DIGEST_CHARS = 320

#: Tool calls kept per turn, and turns kept. A turn that made twenty calls is
#: not twenty things worth remembering — the first few are what it was doing.
MAX_DIGEST_CALLS = 6
MAX_DIGEST_TURNS = 3

_SUMMARY_SYSTEM = (
    "You maintain a running summary of an ongoing conversation between a user "
    "and their assistant. Rewrite the summary so it still fits in a short "
    "paragraph or two, keeping: what the user is working on, decisions they "
    "made, preferences and constraints they stated, and anything left "
    "unfinished. Drop small talk and anything already superseded. Write plain "
    "prose in the third person. Output ONLY the summary."
)


def _heuristic_summary(previous: str, turns: list[dict]) -> str:
    """A free summary: the user's own words, trimmed and stacked.

    Blunt on purpose. It keeps what the user *said* — which is the part a later
    turn is most likely to need — and drops the assistant's prose, which is
    usually reconstructible from it.
    """
    lines = [ln for ln in (previous or "").split("\n") if ln.strip()]
    for turn in turns:
        if turn["role"] != "user":
            continue
        text = " ".join((turn["content"] or "").split())
        if not text:
            continue
        lines.append(f"- The user said: {text[:160]}")
    # Keep the most recent, since the oldest is the most likely to be stale.
    trimmed = lines[-12:]
    return "\n".join(trimmed)[-MAX_SUMMARY_CHARS:]


def _model_summary(provider, previous: str, turns: list[dict]) -> str | None:
    """Ask the model to fold the new turns into the existing summary."""
    transcript = "\n".join(
        f"{t['role']}: {' '.join((t['content'] or '').split())[:600]}" for t in turns)
    if not transcript.strip():
        return previous or None
    body = (f"Existing summary:\n{previous or '(none yet)'}\n\n"
            f"New turns to fold in:\n{transcript}")
    try:
        result = provider.chat(
            [Message(role="system", content=_SUMMARY_SYSTEM),
             Message(role="user", content=body)],
            tools=None, temperature=0.2, max_tokens=400)
    except Exception as exc:
        log.debug("summary model call failed, falling back to heuristic: %s", exc)
        return None
    text = (result.text or "").strip()
    return text[:MAX_SUMMARY_CHARS] or None


def digest_of(trace: list) -> list[dict]:
    """What this turn's tools found, small enough to keep.

    Only the names used to be stored, and the outputs were thrown away — so
    "what was that third result again?" sent the agent to search all over again
    (a fresh turn, so the memo is empty and it pays for it twice) or to
    reconstruct it from its own prose, which is where invented detail comes from.
    """
    pairs: list[dict] = []
    pending: dict | None = None
    for step in trace:
        if step.kind == "tool_call":
            pending = {"name": step.name, "args": step.arguments}
        elif step.kind == "tool_result" and pending is not None:
            text = " ".join((step.result or "").split())
            pending["found"] = text[:MAX_DIGEST_CHARS]
            pairs.append(pending)
            pending = None
        if len(pairs) >= MAX_DIGEST_CALLS:
            break
    return pairs


def _tool_note(rows: list[dict]) -> str:
    """The recent tool findings, as one compact note the model can refer back to."""
    lines: list[str] = []
    for row in rows[-MAX_DIGEST_TURNS:]:
        try:
            entries = json.loads(row.get("tool_json") or "[]")
        except (TypeError, ValueError):
            continue
        for entry in entries:
            # Rows written before results were kept hold a bare list of names.
            if not isinstance(entry, dict):
                continue
            found = (entry.get("found") or "").strip()
            if not found:
                continue
            args = entry.get("args") or {}
            shown = ", ".join(f"{k}={v}" for k, v in list(args.items())[:2])
            lines.append(f"- {entry.get('name')}({shown}) → {found}")
    if not lines:
        return ""
    return ("What your tools found earlier in this conversation (use it instead "
            "of running the same lookup again):\n" + "\n".join(lines[-8:]))


def build_history(mem: AgentMemory, agent: Agent, effort: Effort,
                  provider=None) -> list[Message]:
    """The conversation as the model should see it: a summary, then recent turns.

    Compaction happens here rather than on a timer because this is the only
    place that knows the current window size — which moves when the user changes
    effort level.
    """
    verbatim_rows = mem.history(agent.id, limit=effort.history_verbatim)
    recent = [
        Message(role=r["role"], content=r["content"])
        for r in verbatim_rows
        if r["role"] in ("user", "assistant") and r["content"]
    ]

    oldest_kept = verbatim_rows[0]["ts"] if verbatim_rows else None
    stored = mem.get_summary(agent.id)
    summary = (stored or {}).get("summary") or ""
    covered_to = (stored or {}).get("through_ts")

    pending = mem.messages_before(agent.id, oldest_kept, after=covered_to)
    if len(pending) >= MIN_TO_COMPACT:
        written = None
        if effort.summarise_with_model and provider is not None:
            written = _model_summary(provider, summary, pending)
        if written is None:
            written = _heuristic_summary(summary, pending)
        if written:
            summary = written
            with suppressed("storing the conversation summary"):
                mem.set_summary(agent.id, summary, pending[-1]["ts"])

    messages: list[Message] = []
    note = _tool_note([r for r in verbatim_rows if r.get("tool_json")])
    if note:
        messages.append(Message(role="system", content=note))
    if summary:
        messages.append(Message(
            role="system",
            content=("Earlier in this conversation (summarised — the turns below "
                     "are the verbatim recent ones):\n" + summary),
        ))
    return messages + recent
