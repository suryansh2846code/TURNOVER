# Changing mail that already exists — the contract

> Written alongside the code it describes, per `/CLAUDE.md`. Spans four layers:
> `connectors/`, the action registry, `agents/`, and the card in `web/`.
>
> Sits beside [`connector-permissions.md`](connector-permissions.md), which
> settles *whether an agent may reach Gmail at all*. This settles what it can do
> once it is there.

## 1. Why an agent could not change the inbox

Not a missing feature. **A missing OAuth scope**, and one we had chosen on
purpose.

```python
SCOPES = [
    "…/gmail.readonly",   # read anything
    "…/gmail.send",       # send a NEW message
]
```

The comment above it said so plainly: *"gmail.send can only send, not
read/delete."* That is exactly true, and it is the whole answer. Archiving,
labelling and marking read are not new messages — every one of them is a
**modification of a message that already exists**, and Google puts all of them
behind one scope, `gmail.modify`. We had never asked for it.

So the Inbox agent could read every email, summarise it, draft a reply, send a
reply, and not move one message out of the inbox. It was not confused and it was
not broken; it had read permission and send permission and no change permission.

There was a second, quieter half. Even with the scope, the agent had nothing to
address a message *by*. `gmail_search` syncs matching mail into the brain and
returns **recall** — prose. Prose has no message id. An agent could describe an
inbox in detail and name nothing in it that it could act on.

Both halves had to land together, which is why `list_mail` is part of this
change and not a later nicety.

## 2. The scope we added, and the one we did not

| scope | what it allows | ours |
|---|---|---|
| `gmail.readonly` | read | yes |
| `gmail.send` | send a new message | yes |
| `gmail.modify` | change labels on existing messages; move to trash | **yes, new** |
| `mail.google.com` | everything, including permanent deletion | **no** |

`gmail.modify` is the narrowest scope that allows any of this. It does permit
trashing, and **we expose no verb that trashes**. Nothing in triage needs to
destroy anything: archive takes a message out of the inbox and keeps it. A verb
that deletes mail on the word of a model reading text a stranger wrote is not
one to add because it happened to be in scope. `test_mail_triage.py` pins both:
`delete` is not in `OPERATIONS`, and `mail.google.com` is not in `SCOPES`.

### Existing users have to reconnect once

A token issued before this change carries read and send and nothing else, and
adding a scope to the list does not retrofit it. Left alone, every triage call
would come back 403 from Google, on the far side of a card the user had already
approved.

So `google_auth.may_modify_mail()` reads the token's own scopes and the action
checks it **before it calls Gmail**:

```
Gmail is connected for reading and sending, but not for changing messages.
Reconnect Google under Connectors and approve the extra permission, then this
will work.
```

with `reauth: true`, which the card already renders as a *Reconnect Google*
button. The user is told what to do instead of being shown a permission error
from somebody else's API.

## 3. The unit is the batch, not the message

Triage is where an inbox is twenty decisions at once. Twenty approval cards is
not a safer version of one card — it is the same act with the review worn out of
it by the fourth tap.

So one proposal covers the whole batch:

```xml
<action type="mail_triage">
{"items": [
  {"id": "18f…", "do": "archive",   "subject": "Flash sale ends tonight"},
  {"id": "18g…", "do": "label", "label": "Receipts", "subject": "Invoice 402"},
  {"id": "18h…", "do": "mark_read", "subject": "Standup notes"}
]}
</action>
```

Attributes are flat strings and a list of emails does not fit in one, so the body
is JSON — the same shape `mcp_action` already uses, parsed by the same rules on
both sides. **Malformed JSON is dropped, never guessed at**: no card appears,
rather than a card proposing something nobody wrote.

| field | meaning |
|---|---|
| `id` | Gmail's message id, from `list_mail`. Cannot be guessed; `gmail_search` does not return one. |
| `do` | `archive` · `mark_read` · `mark_unread` · `star` · `unstar` · `label` |
| `label` | required when `do` is `label`; the label is created if the user has none by that name |
| `subject` | carried **only** so the card can name the email without a second round-trip to Gmail while the user is deciding |

Execution groups items by change and issues one `batchModify` per group — three
kinds of change is three requests, not twenty.

### Refused whole, never half

`parse_items` validates the entire batch before anything runs. An unknown verb,
a missing id, a `label` with no label name, or a list that is not a list all
refuse the whole proposal. Applying the valid half would mean the user approved
a card that partly did not happen, which is worse than a clean refusal — and
what they saw on the card is the thing they consented to.

If Gmail itself fails partway through a multi-group batch, the error says how
far it got. *"It failed"* after eight of twelve moved is not the truth.

## 4. What the card says

Counts first, because the number is the decision. Subjects after, because which
ones is the check.

```
Archive 2 emails, Label “Receipts” 1 email        needs your confirmation
  Archive              Flash sale ends tonight
  Archive              Your weekly newsletter
  Label as “Receipts”  Invoice 402 from Northwind
  Nothing is deleted — archiving takes an email out of your inbox and keeps it.
  [ Confirm & apply ]  [ Cancel ]
```

Three rules, each pinned by `test_frontend_mail_card.py`:

* **No message ids.** `18f9a0b2c` means nothing to anyone.
* **No Gmail label ids.** The user reads *Archive*; `REMOVE INBOX` is the
  implementation.
* **Past six emails it gives a count**, not a list nobody reads to the end.

The last line exists because *archive* sounds like *delete* to most people, and
the one thing a person needs to know before tapping is that it is not.

## 5. It never runs unattended

`mail_triage` is in `permissions.NEVER_UNATTENDED`, beside `mcp_action` and
`create_routine`.

This is the exact case `permissions.py` was written for. A triage agent's entire
input is text that strangers sent, and *"archive everything from the bank"* is a
sentence an email can contain. The allow-list that protects `send_email` has
nothing to check here — the messages are already the user's own, so there is no
recipient to compare against anything. The honest answer is that it waits for one
tap, every time.

## 6. Reading well enough to act

| tool | for |
|---|---|
| `list_mail(query, max_results)` | the inbox as addressable rows — id, sender, subject, unread. Gmail query syntax. **The only source of ids.** |
| `read_thread(thread, max_messages)` | one conversation, oldest first, whole |
| `gmail_search(query)` | unchanged — syncs into the brain and returns recall, for *"what did Dana say about the invoice"* |

`read_thread` exists because a search returns the messages that *matched*,
scattered and out of order. A reply only means something against what came
before it, so an agent reading one matched message is reading the end of an
argument and answering as though it were the start.

Both read. Neither changes anything — a change is proposed and waits.

## 7. Permission now covers the user's own inbox

The gate in `loop.py` asked `mcp_tools.connector_of(name)`, which answers for
connector tools and returns `""` for everything else. So an agent had to ask
before reading a Notion page and could read the entire inbox without a word —
the permission model had a hole in the shape of its own motivating example.

`connector_grants.FIRST_PARTY_TOOLS` closes it: a small explicit table of
built-in tools and the connector each reaches, consulted by
`connector_grants.connector_of()` — the one question `loop.py` now asks about
either kind of tool.

```python
FIRST_PARTY_TOOLS = {
    "gmail_search": "gmail", "list_mail": "gmail",
    "read_thread": "gmail",  "calendar_lookup": "gcal",
}
```

A table is a thing that can drift out of date, so `test_mail_triage.py` pins
every name in it against the live tool definitions: a renamed tool that falls
out of this map is a tool that silently stops asking.

`GET /api/agents/{id}/connectors` merges first-party labels into `labels`, so
the `@` picker offers what the gate can refuse. **A connector that is enforced
and not offerable is a dead end with no way out of it.**

## 8. Where each promise lives

| layer | owns |
|---|---|
| `connectors/google_auth.py` | the scopes, `may_modify_mail()`, `NEEDS_MODIFY_SCOPE` |
| `connectors/gmail.py` | `list_inbox`, `read_thread`, `modify_messages`, `ensure_label` |
| `mail_triage.py` | the verbs, validation, grouping, and the card's wording |
| `actions.py` | `_mail_triage` — the approved execution |
| `agents/mail_tools.py` | `list_mail`, `read_thread` |
| `agents/permissions.py` | that it never runs unattended |
| `agents/prompt.py` | the block that teaches one batched proposal |
| `web/chat.js` | parsing the tag and drawing the card |

## 9. Deliberately still open

* **Replying from triage.** Sending already exists as `send_email`; threading a
  reply onto an existing conversation needs `In-Reply-To` and `References`
  headers, and is a separate change.
* **Filters.** Gmail can create a server-side rule that runs without us. That is
  strictly better than a routine for *"always archive this sender"* — and it is
  a different scope (`gmail.settings.basic`) and a different consent.
* **Other mailboxes.** Apple Mail is read-only here and its writes are AppleScript,
  not an API. See [`../MESSAGING.md`](../MESSAGING.md).
