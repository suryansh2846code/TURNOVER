"""Reading an inbox well enough to act on it.

`gmail_search` syncs matching mail into the brain and then returns *recall* —
prose. That is right for "what did Dana say about the invoice" and useless for
triage, because prose has no message id, and every change to a message is
addressed by id. An agent asked to clear an inbox could describe it in detail
and name nothing it could act on.

Two tools, and the split is deliberate:

* `list_mail` — the inbox as a list of addressable rows. Ids, senders, whether
  each is unread. What triage is decided from.
* `read_thread` — one conversation, oldest first, whole. A search returns the
  messages that matched, scattered; a reply only means something against what
  came before it, so an agent reading one matched message is reading the end of
  an argument and answering as if it were the start.

Both read. Nothing here changes anything — a change is proposed as a
`mail_triage` action and waits for the user, which is what
`permissions.NEVER_UNATTENDED` is about: the text these tools return was
written by strangers.
"""
from __future__ import annotations

from ..log import get_logger
from .results import ToolResult

log = get_logger(__name__)

#: Kept small on purpose. A model given eighty rows triages the first ten and
#: summarises the rest, which reads as thoroughness and is not.
DEFAULT_LIMIT = 20
MAX_LIMIT = 60

#: Enough of a message to decide by, without spending the window on newsletters.
SNIPPET_CHARS = 160
BODY_CHARS = 2000


def _gmail():
    """The Gmail connector if it can actually be used, else (None, why)."""
    from ..connectors import get_connector

    connector = get_connector("gmail")
    ready, reason = connector.is_configured()
    if not ready:
        return None, f"Gmail is not connected: {reason}"
    return connector, ""


def _row(item: dict) -> str:
    flags = []
    if item.get("unread"):
        flags.append("unread")
    if item.get("starred"):
        flags.append("starred")
    mark = f" [{', '.join(flags)}]" if flags else ""
    snippet = (item.get("snippet") or "")[:SNIPPET_CHARS].strip()
    return (f"- id={item.get('id')} thread={item.get('thread_id')}{mark}\n"
            f"  from: {item.get('from') or 'unknown'}\n"
            f"  subject: {item.get('subject')}\n"
            f"  {snippet}")


def list_mail(query: str = "in:inbox", max_results: int = DEFAULT_LIMIT) -> ToolResult:
    """Messages matching a Gmail query, each with the id needed to act on it."""
    connector, problem = _gmail()
    if connector is None:
        return ToolResult.failed(problem)

    limit = max(1, min(MAX_LIMIT, int(max_results or DEFAULT_LIMIT)))
    result = connector.list_inbox(query=query or "in:inbox", max_results=limit)
    if not result.get("ok"):
        return ToolResult.failed(f"Gmail could not be read: {result.get('error')}")

    messages = result.get("messages") or []
    if not messages:
        return ToolResult(f"No messages match “{query}”.")

    unread = sum(1 for m in messages if m.get("unread"))
    header = (f"{len(messages)} message(s) matching “{query}” — {unread} unread.\n"
              "Use the id to propose a mail_triage action.")
    return ToolResult(header + "\n" + "\n".join(_row(m) for m in messages))


def read_thread(thread: str, max_messages: int = 20) -> ToolResult:
    """A whole email conversation, oldest first.

    Takes a thread id from `list_mail`. A message id is accepted too and
    resolved to its thread, because a model that has both in front of it will
    reach for the wrong one, and refusing over that teaches nobody anything.
    """
    connector, problem = _gmail()
    if connector is None:
        return ToolResult.failed(problem)

    wanted = str(thread or "").strip()
    if not wanted:
        return ToolResult.failed("Which conversation? Pass a thread id from list_mail.")

    result = connector.read_thread(wanted, max_messages=max_messages)
    if not result.get("ok"):
        return ToolResult.failed(f"That conversation could not be read: "
                                 f"{result.get('error')}")

    messages = result.get("messages") or []
    if not messages:
        return ToolResult.failed(f"No conversation found with id {wanted}.")

    total = result.get("count", len(messages))
    lines = [f"Conversation {wanted} — {total} message(s), oldest first:"]
    for index, message in enumerate(messages, 1):
        body = (message.get("body") or "").strip()[:BODY_CHARS]
        lines.append(
            f"\n[{index}/{total}] {message.get('date') or 'no date'}\n"
            f"from: {message.get('from') or 'unknown'}\n"
            f"to: {message.get('to') or 'unknown'}\n"
            f"{body}")
    text = "\n".join(lines)
    if total > len(messages):
        # `but` replaces the text rather than appending to it, so the note is
        # joined here — appending it any other way would drop the thread.
        text += f"\n\n(Only the first {len(messages)} of {total} are shown.)"
    return ToolResult(text)
