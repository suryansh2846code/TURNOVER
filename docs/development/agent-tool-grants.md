# Which agent can reach which tools — the contract

> Written before the code, per `/CLAUDE.md` ("a change that spans two layers").
> The frontend half is a separate session working from this document, so every
> field is named here, and **ids are named separately from display strings**.
>
> One layer up from [`mcp-contract.md`](mcp-contract.md): that document settled
> what a connector promises the agent layer. This one settles what an *agent*
> has been granted out of it, and how that changes.

## Why this landed

A user connected Notion — remote MCP, signed in, twenty-five working tools —
and asked their agent to summarise a page. It answered out of Notion's
*notification emails* and said the connector was probably still syncing. The
trace was one step: `search_brain`.

Nothing was broken. The agent's stored tools were:

```
["search_brain","remember","list_entities","web_search",
 "add_task","list_tasks","complete_task","gmail_search"]
```

No `mcp` sentinel, so no connector access. It was built before Notion was
connected, and `agents/mcp_tools.py::describe()` returns `[]` when nothing is
connected — deliberately, because a control that cannot do anything reads as a
broken app. So the option did not exist to tick at build time, and **nothing
ever told anyone to go back**.

Four things were missing, and each is a section below:

1. nowhere showed which agent could reach which tools;
2. a custom agent's tools could not be changed at all;
3. a new custom agent defaulted to five tools, connectors not among them, while
   every preset got them;
4. adding a connector granted nothing to agents that already existed, and said
   so to nobody.

---

## 1. Two decisions, made deliberately

### Preset agents are not editable — and the API says so per agent

A preset's tools are code: `library.py` builds each `Template` from `_CORE` plus
its own additions. Making them editable means an overrides table, and an
overrides table has to answer a question this change is not the place to settle:
when a template gains a tool in a later version, does a stale override withhold
it? Answer it wrong and an agent silently stops keeping up with its own
template.

It is also not the reported problem. **Every preset already reaches connectors**,
because `_CORE` carries the sentinel. The failure was a custom agent.

So: `editable: false` on preset rows, with `editable_reason` — a sentence for a
person, returned by the API rather than composed by the UI, so the reason lives
where the decision does.

*Deliberately still open:* there is no "duplicate this preset as my own agent"
path. That is the escape hatch this decision implies and it is not built here.

### New custom agents **do** get connector access

Arguments against, taken seriously: connector access reaches third-party data,
and a default is a permission nobody chose.

Arguments for, which win:

- **A preset gets it.** A custom agent is an agent. Two different defaults for
  the same capability is the kind of accident this document exists to prevent.
- **The sentinel is a standing grant, not a live one.** It resolves to whatever
  is connected *at the time of the turn*. Granting it while nothing is connected
  costs nothing and means the agent works the day a connector is added — which
  is exactly the failure above, in advance.
- **It is visible at the moment it is set.** The builder shows the tool list
  when the agent is created. A default the user can see and untick is a default
  they chose; the one to avoid is the one nobody is shown.

New custom agents therefore default to `library.BASE_TOOLS` — the same base
every preset gets, from the same constant.

**This changes nothing for agents that already exist.** See §5.

---

## 2. `GET /api/agents/{agent_id}/tools`

What this agent has, what it could have, and for anything it cannot have, why.

```jsonc
{
  "agent_id": "chotu",            // id
  "agent_name": "chotu",          // display
  "custom": true,
  "editable": true,
  "editable_reason": "",          // display; non-empty only when editable=false
  "reaches_connectors": false,    // does it have the sentinel, or any connector tool
  "connector_tool_count": 25,     // readable connector tools existing right now
  "tools": [ /* rows, see below */ ]
}
```

### A tool row

```jsonc
{
  "name": "notion_search",   // id — the exact value stored in the agent's list
  "label": "search",         // display — never render `name`
  "description": "…",        // display
  "source": "mcp",           // id: "builtin" | "category" | "mcp"
  "connector": "Notion",     // display label; "" for builtin and category
  "state": "granted",        // "granted" | "available" | "unavailable"
  "via": "category",         // "direct" | "category" | ""
  "reason": ""               // display; see below
}
```

| field | promise |
|---|---|
| `name` | The stored id. **Never rendered.** `source: "mcp"` carries the protocol's acronym and `tests/test_connector_catalog_ui.py` pins that it never reaches the screen — that pin covers this endpoint too. |
| `label` | The only part a person reads. For the sentinel it is *"Everything my connectors can read"*, never `mcp`. |
| `state` | `granted` — the agent has it. `available` — it could be granted. `unavailable` — it cannot be used right now, and `reason` says why. |
| `via` | How a `granted` row is granted. `direct` — `name` is in the stored list. `category` — it resolves through the sentinel and is **not** in the stored list, so unticking it is not a thing the UI can do; unticking the sentinel is. `""` when not granted. |
| `reason` | A sentence for a person. Set when `state` is `unavailable`, and when a `granted` row needs explaining (a sentinel with nothing behind it yet). |

### The sentinel row is always present here

`GET /api/agents/tools` — the global catalogue — omits the sentinel when no
connector is connected, because that endpoint answers *"what can be added right
now"* and offering an empty category is offering nothing.

This endpoint answers a different question: *"what does this agent have, and
what could it have"*. A standing grant with nothing behind it yet is a real
answer to that, and hiding it is what produced the bug at the top of this page.
So the row is always here, and when nothing is connected it says so:

```jsonc
{ "name": "mcp", "label": "Everything my connectors can read",
  "source": "category", "state": "available", "via": "",
  "reason": "No connectors are set up yet. Granting this now covers them as soon as there are." }
```

The two endpoints differ on purpose. Both are honest about their own question.

### A connector that is signed out appears where its tools would

A connector whose server will not answer contributes no tools — `_readable()`
swallows the failure so a broken connector cannot stop an agent answering. That
is right for a turn and wrong for this view, which would silently show nothing
where twenty-five tools used to be.

So each configured connector that is **currently contributing no tools** gets
one row, in the `tools` array, where its tools would have been:

```jsonc
{ "name": "", "label": "Notion", "description": "",
  "source": "mcp", "connector": "Notion",
  "state": "unavailable", "via": "",
  "reason": "Notion is signed out — reconnect it under Connectors." }
```

`name` is empty because **there is nothing to grant** — that is the point of the
row, not an omission. A consumer grouping rows by `connector` renders it in the
place the missing tools would have occupied, which is the only place it means
anything.

Cost: a connector that *is* working produces tools and is never probed. Only the
ones already failing cost a probe, which is exactly when the reason is needed.
The handler is on the `@probes_a_provider` lane for that reason.

---

## 3. `PATCH /api/agents/custom/{agent_id}`

A real update. Delete-and-recreate would lose the agent's chat history (keyed by
`agent_id` in `agent_messages`) and its model binding (`agent_model_configs`) —
so it is not an implementation detail that this is a `PATCH`.

```jsonc
// request — every field optional; absent means "leave it alone"
{ "tools": ["search_brain", "mcp"],
  "name": "…", "role": "…", "system_prompt": "…", "recall_sources": ["notion"] }
```

* `404` if the id is not a custom agent — **including when it is a preset**, so
  the boundary is enforced by the server and not by the UI remembering to.
* `400` naming every unknown tool id, rather than dropping them silently. An id
  is accepted if it is a built-in, the sentinel, or a connector tool that
  resolves right now.
* The **id never changes**, whatever happens to `name`. The id is what the chat
  history and the model binding are keyed by.
* Returns the same envelope as `GET /api/agents/{agent_id}/tools`, so the caller
  needs no second round trip to redraw.

---

## 4. `GET /api/agents` gains one field

```jsonc
{ "id": "chotu", …, "reaches_connectors": false }
```

One boolean, so a list of agents can show which ones cannot reach the
connectors the user has — without the caller re-deriving it from `tools` and the
sentinel, which is a rule that would then exist in two places.

---

## 5. `GET /api/agents/connector-gaps`

The answer to *"I just connected something — who cannot use it?"*

```jsonc
{
  "connectors": ["Notion", "Linear"],   // display labels, currently readable
  "tool_count": 25,
  "agents": [                            // only those that cannot reach any of it
    { "agent_id": "chotu", "agent_name": "chotu",
      "custom": true, "editable": true, "editable_reason": "" }
  ]
}
```

`agents: []` means there is nothing to say and the caller should say nothing.

**This endpoint reads. It never grants.** Connector access is a permission the
user sets, and an agent that already exists was configured by somebody who did
not tick this box — quietly ticking it later because we added a feature is
exactly the kind of change `/CLAUDE.md` means by *"never surface an internal"*
turned inside out: it would be surfacing nothing while changing something.

So: surfacing the gap is in scope, closing it without asking is not. The caller
shows the list and a way to act on it; each act goes through §3.

---

## 6. Where each promise lives

| layer | owns |
|---|---|
| `agents/library.py` | `BASE_TOOLS` — the one definition of what every agent starts with, preset or custom |
| `agents/grants.py` | the per-agent view: states, reasons, and which connectors are contributing nothing |
| `agents/custom.py` | `update()` — the real update, id-preserving |
| `api/routes/agents.py` | the three endpoints, thin over the above |

`agents/grants.py` is new and deliberately not in `tools.py`: `describe_tools()`
answers "what exists", this answers "what does *this agent* have", and the
second is not a filter over the first — it needs the agent, the sentinel's
resolution, and the connector's health.
