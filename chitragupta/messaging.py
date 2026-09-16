"""Every conversation the user has, behind one shape.

Mail got `list_mail` / `read_thread` / one batched action, and the obvious next
question was "do the same for Telegram and Slack". Doing it twice would produce
two of everything — two tools, two actions, two cards — for a difference the
user does not care about: a message is a message, and which app carried it is a
detail of where it came from.

So a connector that can carry a conversation implements three methods, and this
module is the only thing that knows which connectors those are. Adding an app
means writing one class; nothing in `agents/` changes.

    chats(limit)             -> list[Chat]      what conversations exist
    history(chat_id, limit)  -> list[Message]   one conversation, oldest first
    send(chat_id, text)      -> dict            WRITE, after one tap

Duck-typed rather than a base class, the same way `actions._writer` finds
`send_email`: a connector that only ingests is a perfectly good connector, and
inheriting three `NotImplementedError`s to say so helps nobody.

**Ordering is a promise.** `history` returns oldest first, always. Every chat
API returns newest first because that is what a chat window wants, and an agent
handed a reversed conversation reads the argument backwards and answers the
first message it sees as though it were the last.

Which apps are reachable at all, and why WhatsApp and LinkedIn are not:
`docs/MESSAGING.md`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .log import get_logger, suppressed

log = get_logger(__name__)


@dataclass(frozen=True)
class Chat:
    """One conversation, in terms that are the same on every app."""

    id: str
    name: str
    #: "dm" · "group" · "channel". What a person would call it, not what the
    #: vendor calls it — Slack's `im`, Telegram's `User` and a WhatsApp
    #: one-to-one are the same thing to somebody deciding whether to reply.
    kind: str = "dm"
    unread: int = 0


@dataclass(frozen=True)
class Message:
    id: str
    sender: str
    #: ISO 8601. Chat APIs disagree about epochs, floats and strings; they
    #: disagree here too, and this is where it stops.
    at: str
    text: str
    #: Did the user write it? The single most useful bit for an agent deciding
    #: whether a conversation is waiting on them.
    outgoing: bool = False


@runtime_checkable
class Messenger(Protocol):
    """What a connector adds to become a place conversations happen."""

    name: str
    label: str

    def chats(self, limit: int = 30) -> list[Chat]: ...
    def history(self, chat_id: str, limit: int = 50) -> list[Message]: ...
    def send(self, chat_id: str, text: str) -> dict: ...


def _carries_conversations(connector: Any) -> bool:
    return all(callable(getattr(connector, m, None))
               for m in ("chats", "history", "send"))


def apps() -> list[Any]:
    """Every messaging connector the user has actually set up.

    Configured only. Offering a control that cannot do anything is the one
    thing `/CLAUDE.md` is most explicit about, and an agent told it can reach
    Slack when no token exists produces the same failure in the model's words.
    """
    from .connectors import REGISTRY, get_connector

    out: list[Any] = []
    for name in REGISTRY:
        with suppressed("checking whether a connector carries conversations"):
            connector = get_connector(name)
            if not _carries_conversations(connector):
                continue
            ready, _reason = connector.is_configured()
            if ready:
                out.append(connector)
    return out


def app_ids() -> list[str]:
    return [a.name for a in apps()]


def get_app(name: str) -> Any | None:
    """One messaging connector by id, if it is set up and can carry messages."""
    wanted = str(name or "").strip().lower()
    for connector in apps():
        if connector.name == wanted:
            return connector
    return None


def labels() -> dict[str, str]:
    """App id -> the name a person reads."""
    return {a.name: str(getattr(a, "label", a.name)) for a in apps()}


def target(app: str, chat: str) -> str:
    """The comparable form of "this conversation on this app".

    Scoped by app on purpose. Allowing `@dana` on Telegram must not also allow
    a `#dana` in Slack — they are different people as often as not, and a
    permission the user granted in one place silently spanning another is the
    kind of thing an allow-list exists to prevent.
    """
    return f"{str(app or '').strip().lower()}:{str(chat or '').strip().lower()}"


def describe_chat(app_label: str, chat: Chat) -> str:
    """One line for a tool result: what this conversation is."""
    flag = f" [{chat.unread} unread]" if chat.unread else ""
    return f"- id={chat.id} · {chat.name} ({app_label} {chat.kind}){flag}"
