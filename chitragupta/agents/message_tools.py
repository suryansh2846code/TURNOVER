"""Reading the user's conversations — whichever app they are on.

One pair of tools across every messaging app, not one pair per app. The user
does not think "my Slack question" and "my Telegram question"; they think
"did Dana ever reply". Two of everything for a difference nobody is asking
about is how a tool list becomes twenty entries that mean four things.

The gate is the interesting part. `loop.py` blocks a tool by NAME, which works
for `list_mail` — it reaches Gmail and nothing else. It cannot work here: which
connector `read_chat` reaches depends on the `app` argument, which the gate
never sees. So these tools ask for themselves, using the same single function
`loop.py` uses, and the answer is the same answer:

* an app the agent may use is listed and readable;
* an app it may not is **named, and said to need permission** — never silently
  dropped, because an agent that cannot see Slack tells the user there is no
  Slack, which is false and unfixable from the user's side.

Writing is not here. A message that leaves the machine is proposed as a
`message_send` action and waits for a tap.

Which apps exist at all: `docs/MESSAGING.md`.
"""
from __future__ import annotations

# The module, not the names. Binding `apps` at import time would freeze the
# answer to "which apps are connected" at the moment this file was first
# loaded — so connecting Telegram mid-session would change nothing until a
# restart, which is the same class of bug as gating a tool on a stale catalogue.
from .. import messaging
from ..log import get_logger
from ..messaging import describe_chat
from .results import ToolResult

log = get_logger(__name__)

#: Enough conversation to judge by. An agent handed a thousand messages
#: summarises the first page and presents that as the answer.
DEFAULT_CHATS = 25
DEFAULT_MESSAGES = 40
MAX_MESSAGES = 100
TEXT_CHARS = 1200

NOTHING_CONNECTED = (
    "No messaging apps are connected. Telegram and Slack can be added under "
    "Connectors. Tell the user that rather than guessing at their messages.")


def _permitted() -> tuple[list, list[str]]:
    """(apps this agent may use, names of the ones it must ask about first)."""
    from . import connector_grants

    who = connector_grants.acting()
    allowed, blocked = [], []
    for connector in messaging.apps():
        if connector_grants.may_use(who, connector.name):
            allowed.append(connector)
        else:
            blocked.append(str(getattr(connector, "label", connector.name)))
    return allowed, blocked


def _ask_for(blocked: list[str]) -> str:
    if not blocked:
        return ""
    names = ", ".join(blocked)
    return (f"\n\n{names} is also connected but you need the user's permission "
            f"to read it. Ask them for it and say what you want it for.")


def list_chats(app: str = "") -> ToolResult:
    """The user's conversations, across every messaging app they connected."""
    allowed, blocked = _permitted()

    wanted = str(app or "").strip().lower()
    if wanted:
        allowed = [a for a in allowed if a.name == wanted]
        if not allowed:
            if any(b.lower() == wanted for b in blocked):
                return ToolResult.failed(
                    f"You need the user's permission to read {wanted}. Ask them.")
            return ToolResult.failed(
                f"“{app}” is not a messaging app the user has connected.")

    if not allowed:
        return ToolResult.failed(NOTHING_CONNECTED + _ask_for(blocked))

    lines: list[str] = []
    problems: list[str] = []
    for connector in allowed:
        label = str(getattr(connector, "label", connector.name))
        try:
            found = connector.chats(limit=DEFAULT_CHATS)
        except Exception as exc:
            problems.append(f"{label} could not be read: {str(exc)[:120]}")
            continue
        if not found:
            continue
        lines.append(f"\n{label} — {len(found)} conversation(s):")
        lines += [describe_chat(connector.name, chat) for chat in found]

    if not lines:
        body = "No conversations found." if not problems else "\n".join(problems)
        return ToolResult.failed(body + _ask_for(blocked))

    header = ("Use `read_chat` with the app and the id to read one. "
              "To send, propose a message_send action.")
    tail = ("\n\n" + "\n".join(problems) if problems else "") + _ask_for(blocked)
    return ToolResult(header + "\n" + "\n".join(lines) + tail)


def read_chat(app: str, chat: str, limit: int = DEFAULT_MESSAGES) -> ToolResult:
    """One conversation, oldest first, so it reads in the order it happened."""
    from . import connector_grants

    wanted = str(app or "").strip().lower()
    chat_id = str(chat or "").strip()
    if not wanted or not chat_id:
        return ToolResult.failed(
            "Which conversation? Pass the app and the id from `list_chats`.")

    connector = messaging.get_app(wanted)
    if connector is None:
        return ToolResult.failed(
            f"“{app}” is not a messaging app the user has connected.")
    if not connector_grants.may_use(connector_grants.acting(), connector.name):
        label = str(getattr(connector, "label", connector.name))
        return ToolResult.failed(
            f"You need the user's permission to read {label}. Ask them for it "
            "and say what you want it for.")

    try:
        found = connector.history(chat_id, limit=max(1, min(MAX_MESSAGES, int(limit))))
    except Exception as exc:
        return ToolResult.failed(f"That conversation could not be read: "
                                 f"{str(exc)[:160]}")
    if not found:
        return ToolResult("That conversation has no messages in it yet.")

    label = str(getattr(connector, "label", connector.name))
    lines = [f"{label} conversation {chat_id} — {len(found)} message(s), "
             "oldest first:"]
    for message in found:
        who = "the user" if message.outgoing else message.sender
        lines.append(f"\n[{message.at or 'no date'}] {who}:\n"
                     f"{message.text[:TEXT_CHARS]}")
    return ToolResult("\n".join(lines))
