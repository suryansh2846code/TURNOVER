# Asking to use a connector — the contract

> Written before the code, per `/CLAUDE.md` ("a change that spans two layers").
> This one spans four: `agents/`, `api/`, `web/`, and the composer.
>
> Sits on top of [`agent-tool-grants.md`](agent-tool-grants.md), which settled
> *which tools an agent holds*. This settles *whether it may use one right now*.

## Why this exists

An agent holding the connector category can read everything the user has
connected, on any turn, without saying so. That was the right call when the
category was the only way to reach a connector at all. It is the wrong shape
once agents are specialists the user assembles: adding a Writer should not
silently hand it the inbox.

The line drawn here is **not** "trust the agent less". It is that reaching a
third-party account is a thing the user should be able to see happening, and
decide about, per agent — while never being asked twice about something they
have already settled.

## 1. Three ways an agent gets to use a connector

| | how long | where it is set |
|---|---|---|
| **once** | this turn only | the user taps *Allow once*, or `@`-mentions the connector in the message |
| **always** | until revoked | the user taps *Always allow*, stored per `(agent_id, connector)` |
| **unrestricted** | permanently, by design | a template declares it — only Chief of Staff |

Nothing is granted by adding an agent. A card saying *"Works with Gmail"*
describes what the agent is **for**, not what it may already do.

## 2. Chief of Staff is the exception, and it is a declared one

`Template.unrestricted_connectors` — a field, not a hardcoded id, so the
exception is visible in the library beside the agent that has it and a second
generalist would not need a code change to behave the same way.

It is the agent the user adds knowing it is the one that can do anything; its
card already says it runs code and can retract facts. Asking permission on every
turn for the agent whose entire job is "whatever you need" would be a prompt
nobody reads, which is worse than not asking.

## 3. What the agent experiences

The connector tools are **offered** to it, and **gated at execution**. Not
hidden — an agent that cannot see the tool tells the user it cannot read email,
which is false: it can, with one tap. So it tries, and gets back:

```
Needs your permission: reading Gmail. Ask the user to allow it — say what you
want it for. Do not try another connector instead.
```

That is a `ToolResult` with `ok=False`, so the existing failure path carries it:
the retry nudge fires, the turn ends with the agent asking in its own words, and
the request is surfaced as a card.

## 4. What the user sees

A **permission card**, the same shape as an action card:

```
Inbox wants to read your Gmail
  To find the thread from Dana you asked about.
  [ Allow once ]  [ Always allow ]  [ No ]
```

* **Allow once** — grants for the next turn, then re-runs the question.
* **Always allow** — stores `(inbox, gmail)` and re-runs.
* **No** — records nothing; the agent is told and answers without it.

Granting re-runs the turn rather than leaving the user to retype, reusing the
resume path built for approved actions (`agents/outcomes.py`).

## 5. `@` in the composer

Typing `@` — or the name of a connector — offers a picker of what is connected.
Choosing one attaches it to **that message only**:

```
@gmail  what did Dana say about the invoice?
```

The chip is visible in the composer before sending, because a grant the user
cannot see before they send it is not a grant they made.

On the wire it is `ChatIn.connectors: list[str]` — ids, not display labels. The
composer shows labels; the request carries ids.

## 6. What the API promises

| endpoint | promise |
|---|---|
| `GET /api/agents/{agent_id}/connectors` | what this agent may use, and what it would have to ask for |
| `POST /api/agents/{agent_id}/connectors` | `{connector, scope}` — `always` stores it, `once` is not stored and is refused here |
| `DELETE /api/agents/{agent_id}/connectors/{connector}` | revoke an `always` |

`POST /api/agents/{id}/chat` and `/chat/stream` grow `connectors` — the
one-message grants from `@`.

Every one is added to `tests/api_surface.json` in the same commit.

## 7. Where each promise lives

| layer | owns |
|---|---|
| `agents/connector_grants.py` | the store, and the one function that answers "may this agent use this connector right now" |
| `agents/loop.py` | the gate — checked before a connector tool executes, never by the model |
| `agents/library.py` | `unrestricted_connectors`, and the card field that says so |
| `api/routes/agents.py` | the three endpoints, and threading one-message grants into the turn |
| `web/chat.js` | the `@` picker, the chips, the permission card |

## 8. Deliberately decided

**The gate is at execution, not in the prompt.** A model told "ask first" will
sometimes not. `loop.py` checks before it runs, so the rule holds whatever the
model does — the same reason the outbound allow-list is not a prompt.

**Reads are what this governs.** A connector *write* already goes through
propose → confirm, and that is unchanged: a granted connector still shows an
action card before it changes anything. Grant and confirmation compose; neither
replaces the other.

**`once` is not stored.** It lives for one turn. Persisting it would turn "just
this time" into a thing the user has to remember to undo.

**A revoked or never-granted connector is never silently skipped.** The agent is
told, in words it can pass on. Silence here would produce the answer this whole
project started with: a confident reply built from the wrong source.

## 9. Deliberately still open

* **Per-tool grants.** The unit is the connector, not the tool. "Gmail but only
  search" is a finer line than anyone has asked for, and finer lines are how a
  permission screen becomes one nobody reads.
* **Time-boxed grants** ("for the next hour"). `once` and `always` cover what
  has been asked for; a third scope needs a reason first.
