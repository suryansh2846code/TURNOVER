"""Changing mail that already exists — the vocabulary, in one place.

An agent could compose and send email for as long as this project has existed
and still could not archive a single message. The reason was never the code: it
was the OAuth scope. `gmail.send` can *only* send — it cannot touch a message
that already exists — and archiving, labelling and marking read are all
modifications of an existing message. Google puts every one of them behind
`gmail.modify`, which we had deliberately not asked for.

Two consequences shape this module:

* **A token issued before that change cannot do any of this.** It is not an
  error to explain away — the user has to reconnect Google once. Everything
  here checks first and says so, rather than proposing a card that will 403.
* **The unit is the batch, not the message.** Triage is where an inbox is
  twenty decisions, and twenty approval cards is not a safer version of one —
  it is the same act with the review worn out of it. One card names every
  message it covers, and one `batchModify` applies it.

Deliberately not here: trashing. `gmail.modify` permits it and we expose no
verb for it. Nothing in triage needs to destroy anything — archive removes a
message from the inbox and keeps it — and a verb that deletes mail on the word
of a model reading text a stranger wrote is not one to add casually.

Contract: `docs/development/mail-triage.md`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Operation:
    """One thing that can be done to a message, in Gmail's terms and the user's."""

    #: What the card says. A verb a person recognises, never a label id.
    verb: str
    #: Gmail system labels to add / remove. Gmail models all of this as labels:
    #: archiving is removing INBOX, marking read is removing UNREAD.
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()
    #: Needs a label name from the proposal (`label` is the only one).
    names_a_label: bool = field(default=False)


OPERATIONS: dict[str, Operation] = {
    "archive":     Operation("Archive", remove=("INBOX",)),
    "mark_read":   Operation("Mark read", remove=("UNREAD",)),
    "mark_unread": Operation("Mark unread", add=("UNREAD",)),
    "star":        Operation("Star", add=("STARRED",)),
    "unstar":      Operation("Unstar", remove=("STARRED",)),
    "label":       Operation("Label", names_a_label=True),
}

#: Beyond this, the card stops naming individual messages and gives a count.
#: A list nobody reads to the end is not more informative than its length.
MAX_NAMED_ON_CARD = 6


def parse_items(raw: object) -> tuple[list[dict], str]:
    """Clean the proposed items, or say what is wrong with them.

    Returns `(items, error)`. Anything unparseable is refused whole rather than
    partly applied — half of a triage is worse than none of it, because the
    user approved a thing that did not happen.
    """
    if isinstance(raw, dict):
        raw = raw.get("items")
    if not isinstance(raw, list) or not raw:
        return [], "No emails were listed to act on."

    items: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            return [], "One of the emails was not described properly."
        message_id = str(entry.get("id") or "").strip()
        verb = str(entry.get("do") or "").strip().lower()
        if not message_id:
            return [], "One of the emails had no id, so there is nothing to change."
        operation = OPERATIONS.get(verb)
        if operation is None:
            known = ", ".join(sorted(OPERATIONS))
            return [], f"“{verb or 'nothing'}” is not something I can do to an email. I can: {known}."
        label = str(entry.get("label") or "").strip()
        if operation.names_a_label and not label:
            return [], "A label was asked for without saying which label."
        items.append({
            "id": message_id,
            "do": verb,
            "label": label,
            # Carried only so the card can name the email without a second
            # round-trip to Gmail at the moment the user is deciding.
            "subject": str(entry.get("subject") or "").strip(),
        })
    return items, ""


def group(items: list[dict]) -> dict[tuple[str, str], list[str]]:
    """Message ids grouped by the change to apply — one batch call each."""
    batches: dict[tuple[str, str], list[str]] = {}
    for item in items:
        batches.setdefault((item["do"], item["label"]), []).append(item["id"])
    return batches


def summarise(items: list[dict]) -> str:
    """The card's line: what is about to happen, in the user's words.

    Counts first, because the number is the decision. Subjects after, because
    which ones is the check.
    """
    if not items:
        return "Nothing to change"
    # Reads with `.get`, because this is called on raw proposed items as well
    # as parsed ones — the approval card summarises what the model wrote before
    # anything has validated it, and a card that raises shows the user nothing.
    counts: dict[str, int] = {}
    for item in items:
        operation = OPERATIONS.get(str(item.get("do") or ""))
        verb = operation.verb if operation else "Change"
        label = str(item.get("label") or "")
        name = f"{verb} “{label}”" if label else verb
        counts[name] = counts.get(name, 0) + 1
    parts = [f"{verb} {n} email{'s' if n != 1 else ''}" for verb, n in counts.items()]
    line = ", ".join(parts)

    named = [str(i.get("subject")) for i in items if i.get("subject")][:MAX_NAMED_ON_CARD]
    if not named:
        return line
    tail = "" if len(items) <= len(named) else f", +{len(items) - len(named)} more"
    return f"{line} — {'; '.join(named)}{tail}"
