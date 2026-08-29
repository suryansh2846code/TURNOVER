# Lodestone — The Complete Project Explainer

> A from-scratch, plain-English walkthrough of **what** we built, **how** it
> works, and **why** every decision was made. Read this top to bottom and you
> will understand the whole project, even the parts that look like magic.

Repo: https://github.com/suryansh2846code/TURNOVER
Status: v0.2, runs locally, agents reason on a free local model.

---

## 0. The one-sentence version

**Lodestone is a private AI workspace that lives on your computer. It reads your
own data into a "brain," and lets specialized AI agents answer and act using
that brain — so the AI already knows you and you never have to re-explain
yourself.**

It is an open competitor to [Turnstone](https://myturnstone.ai) (YC W26).

---

## 1. The problem (why this exists at all)

Every time you open ChatGPT, Claude, or Cursor, the AI is a stranger. It doesn't
know:

- who you are, what you're building, who your teammates are,
- what you said yesterday, what's in your email, your files, your notes,
- your preferences (tools you like, tone you want).

So you **re-explain yourself constantly**. You paste the same context. You start
over with every model. Your knowledge is scattered across apps and locked inside
each vendor's cloud.

**The insight:** separate two things that are usually glued together —

| Thing | Who should own it | Where it should live |
|-------|-------------------|----------------------|
| Your **context** (memory of you) | You | Your machine |
| The **model** (the reasoning engine) | Swappable vendor | Anywhere |

If your context is yours and local, and the model is a swappable part, then any
AI can plug into your context. That's the whole thesis. Lodestone is the layer
that owns your context and feeds it to whatever model you bring.

---

## 2. What Turnstone actually is (and how we figured it out)

We initially misread Turnstone as a *passive memory box* that other apps query.
After deeper research (their site, YC page, founders) we corrected it:

**Turnstone is an active AI workspace — a Mac app you live inside.** It has three
pillars, and Lodestone mirrors all three:

1. **A Brain** — connect your apps (Gmail, Drive, Notion, iMessage, browser,
   local folders); it continuously indexes them into one local knowledge base.
2. **Named agents** — Inbox, Launch, Research, Personal. Each is focused on a
   domain, remembers its own work, and *all share the one brain* — so what one
   learns makes the others smarter.
3. **Bring your own model** — agents run on models you already pay for
   (ChatGPT/Claude/Cursor subscription, API keys, OpenRouter, or free local).

> ⚠️ Naming trap we hit: the `turnstonelabs/turnstone` project on GitHub is a
> *different, unrelated* tool (cluster agent-orchestration). The one we're
> cloning is **myturnstone.ai**, the YC W26 desktop workspace.

---

## 3. The big decisions, and why (the decision log)

This is the heart of "why every step was taken."

### Decision 1 — Build it as a portfolio piece, cloning Turnstone's *engine*
**Why:** It exercises the most in-demand AI-engineering skills (connectors,
retrieval, agents, tool-use, multi-model) and demos in one screen. The category
is crowded, but for a portfolio *how well you build it* matters more than
novelty.

### Decision 2 — Stack: Python + FastAPI + web UI (not Node, not desktop-first)
**Why:** Fastest path to a working demo; mirrors Turnstone's own Python stack.
Crucially, a **web-first engine can be wrapped in a desktop app later with zero
rewrite** — a Tauri/Electron shell just bundles this same server as a "sidecar."
So we don't choose web *instead of* app; we choose web *now*, app *later*.

### Decision 3 — First attempt was WRONG: a passive MCP memory server
We first built a "brain other tools query over MCP." That's not Turnstone.
**Why we scrapped it:** Turnstone is where you *do the work*, not a plugin for
other tools. The user caught this. We restarted **agent-first**.

### Decision 4 — Agent-first re-architecture
Agents became the core primitive, not an afterthought. Everything else (brain,
models, tools) exists to serve agents.
**Why:** It matches what the product actually is — you talk to agents that act.

### Decision 5 — Knowledge-graph brain (not just plain vector search)
The brain stores **both** raw recallable text *and* a graph of entities
(people/projects/tools) and facts connecting them.
**Why:** Turnstone hints at a knowledge graph. Graphs answer "who/what/how are
these related" that flat search misses, and make recall more precise.

### Decision 6 — Bring-your-own-model with a provider abstraction
One interface, many backends: Claude, OpenAI, OpenRouter, Ollama, a
subscription-gateway slot, and an offline "mock."
**Why:** "BYO model" is Turnstone's core promise. An abstraction means the agent
code never changes when you swap models. The **mock** provider means the whole
app is testable with zero keys and zero network.

### Decision 7 — Run on a free LOCAL model (Ollama) by default
**Why:** Most on-brand for a local-first, private product. No API keys, no cost,
nothing leaves the machine. We used `llama3.2` (small, fast, free).

### Decision 8 — Auto-recall on every turn (don't trust the model to ask)
Small models unreliably choose to call the "search my brain" tool. So **before**
the model runs, we inject the relevant brain slice automatically.
**Why:** Guarantees agents "already know you" regardless of model size. Tools
stay available for going *deeper*; the baseline context is always present.

### Decision 9 — Auto-learn from conversation
After each turn, we quietly extract durable facts the user revealed and save
them to the shared brain.
**Why:** This answers "how does it automate if I must tell it everything?" — you
don't. Just talking grows the brain, and a fact told to one agent is known by
all.

### Decision 10 — Connectors build the graph, with fast offline extraction
Syncing a folder/email routes through the brain and extracts entities+facts —
using a fast heuristic (no per-chunk model call) for bulk imports.
**Why:** One folder sync should yield hundreds of facts instantly, not hammer
the model hundreds of times. (Proven: one real project folder → 292 memories,
834 entities, 1266 facts.)

### Decision 11 — A real folder picker (not "type an exact path")
**Why:** The text-prompt path entry caused "no files found." A local app should
let you *browse and click*. We added a read-only filesystem browser + modal.

---

## 4. Architecture — the map

```
        ┌──────────────── Workspace UI (browser) ─────────────────┐
        │  Agent tabs   |   Chat + live tool trace   |   Brain panel │
        └───────────────────────────┬──────────────────────────────┘
                                     │  HTTP (FastAPI)
        ┌────────────────────────────┼───────────────────────────────┐
        ▼                            ▼                               ▼
  ┌───────────┐            ┌──────────────────┐            ┌────────────────┐
  │  Agents   │  uses ───▶ │  Model providers │            │     Brain      │
  │ runtime   │            │  (BYO model)     │            │  ┌───────────┐ │
  │  + tools  │            │ claude/openai/   │            │  │ vector    │ │
  │           │            │ openrouter/      │            │  │ memories  │ │
  │ Inbox     │            │ ollama/          │            │  ├───────────┤ │
  │ Launch    │            │ subscription/    │            │  │ knowledge │ │
  │ Research  │            │ mock             │            │  │ graph     │ │
  │ Personal  │            └──────────────────┘            │  └───────────┘ │
  └─────┬─────┘                                            └───────▲────────┘
        │ tools: search_brain, remember, web_search,               │ ingest +
        │        gmail_search, list_entities                       │ extract
        └──────────────────────────────────────────────┐          │
                                              Connectors │──────────┘
                                   files · notes · gmail · notion · gdrive
```

Folder map:

```
lodestone/
  config.py            # settings from env/.env, local defaults
  core/                # low-level plumbing
    db.py              #   SQLite schema (memories, entities, relations)
    store.py           #   MemoryStore: add/search memories (vector + lexical)
    embeddings.py      #   turn text → vectors (hash/local/openai/gemini)
    chunk.py           #   split long text into embeddable pieces
  brain/               # THE BRAIN
    brain.py           #   ingest() writes memories+graph; recall() fuses them
    graph.py           #   entities + relations (knowledge graph ops)
    extract.py         #   pull entities/facts from text (LLM or heuristic)
  models/              # BRING YOUR OWN MODEL
    base.py            #   Message/Tool/ToolCall + LLMProvider interface
    anthropic.py       #   Claude
    openai_compat.py   #   OpenAI, OpenRouter, Ollama (one impl)
    registry.py        #   pick provider from config; subscription slot; mock
  agents/              # THE AGENTS
    agent.py           #   Agent definition + persistent per-agent chat memory
    presets.py         #   Inbox, Launch, Research, Personal
    tools.py           #   the tools agents can call
    runtime.py         #   the model+tool loop; auto-recall; auto-learn
  connectors/          # DATA IN
    files, notes, gmail, notion, gdrive
  api/app.py           # FastAPI: chat, brain, connectors, fs-browse
  web/                 # the workspace UI (index.html, styles.css, app.js)
  cli.py               # serve / chat / ingest / stats / providers
```

---

## 5. The Brain, explained from basics

The brain answers one question well: *"Given what the user is asking, what do we
already know that's relevant?"* It uses **two complementary techniques.**

### 5a. Vector memories (semantic search)
- **Embedding** = turning text into a list of numbers (a "vector") that captures
  meaning. Similar meanings → nearby vectors.
- We store every chunk of your data as text + its vector in SQLite.
- To recall, we embed your query and find the closest stored vectors (cosine
  similarity). That surfaces relevant text even if the words don't match exactly.
- We also add a **lexical overlap** boost so exact keywords aren't missed.
- **Embeddings are pluggable.** Default `hash` needs no downloads/keys (lexical
  quality, works offline). Upgrade to `local` (a real model), `openai`, or
  `gemini` for true semantic quality — recall code doesn't change.

### 5b. Knowledge graph (structured facts)
- Flat text search can't cleanly answer "what tools does project X use?"
- So on ingest we also **extract entities** (people, projects, tools, orgs) and
  **relations/facts** between them, storing them as a graph.
- Extraction uses the LLM when available (accurate) and falls back to a
  **heuristic** (capitalized noun phrases + sentence facts) when offline — so
  the graph builds even with zero keys.
- On recall we match query → entities → their facts, and include that structured
  summary alongside the raw memories.

### 5c. Fused recall
`Brain.recall(query)` returns one block:
```
KNOWN ENTITIES & FACTS:
 • WhatsApp Agent (project): built on Cloudflare Workers, Groq, Meta API, Sheets
RELEVANT MEMORIES:
 [notes:projects] The WhatsApp agent is a multi-tenant assistant ...
```
This block is what gets injected into the model. It is **token-budgeted** so it
never overflows the model's context window.

---

## 6. Bring Your Own Model, explained

Every model vendor speaks a slightly different "wire format." We hide that behind
one `LLMProvider.chat(messages, tools)` interface that returns a normalized
result (text + any tool calls). Consequences:

- **Agents are model-agnostic** — the same agent runs on Claude or a local model.
- Adding a model = writing one small adapter.
- `openai_compat.py` covers OpenAI, OpenRouter, and Ollama at once (they share
  the `/chat/completions` + tools format).
- **subscription** provider = a slot that points at a local gateway holding your
  paid ChatGPT/Claude session (the hard, ToS-sensitive path Turnstone
  advertises). We treat it as pluggable rather than reverse-engineering each
  vendor's private auth.
- **mock** provider = deterministic, offline; lets us test the entire agent loop
  with no network and no keys.

Pick the backend with one env var: `LODESTONE_MODEL_PROVIDER`.

---

## 7. Agents, explained

An **Agent** is: a name + a focus + a system prompt + a set of tools + its own
persistent chat history. The four presets mirror Turnstone: **Inbox, Launch,
Research, Personal.** They differ in prompt and tools but **share one brain.**

### The agent turn (what happens when you send a message)

```
1. AUTO-RECALL: brain.recall(your message) → inject relevant context up front
2. Load this agent's recent chat history (its own memory)
3. Ask the model: here's your role, your context, the conversation, and your tools
4. LOOP (up to 5 steps):
     - if the model wants to call a tool (search_brain, web_search, gmail_search,
       remember, list_entities) → run it, feed the result back, repeat
     - else → we have the final answer, stop
5. Save the reply to this agent's memory
6. AUTO-LEARN: scan your message for durable facts → save them to the shared brain
```

Steps 1 and 6 are the "magic": the agent starts already knowing you (1) and gets
smarter just by talking to you (6). The UI shows steps as a **trace**
(`auto_recall`, `search_brain`, `auto_learn`) so the behavior is visible, not
hidden.

---

## 8. How data gets into the brain (3 ways)

| Way | You do | Automatic part | Built? |
|-----|--------|----------------|--------|
| **Connectors** | Connect a source once (a folder, Gmail, Notion, Drive) | Reads real data, extracts hundreds of facts | ✅ (manual trigger) |
| **Auto-learn** | Just chat naturally | Durable facts saved to the shared brain | ✅ |
| **Manual box** | Type a one-off fact | — | ✅ |
| **Continuous sync** | Nothing | Re-index changed sources on a timer | ⏳ next |

**The point:** you don't feed it manually. Connectors do the bulk; conversation
does the rest.

---

## 9. How to run it

```bash
cd ~/workspace/lodestone
ollama serve &                 # start the free local model server
source .venv/bin/activate
lodestone serve                # workspace → http://127.0.0.1:8787
```

Then: pick an agent, chat; use the right panel to add facts, browse the knowledge
graph, and sync a folder via the picker.

CLI shortcuts:
```bash
lodestone agents               # list the 4 agents
lodestone chat research "what do I build?"
lodestone ingest --path /Users/you/notes
lodestone stats                # brain + graph counts
lodestone providers            # model backends + readiness
```

Switch models via `.env`:
```
LODESTONE_MODEL_PROVIDER=ollama     # or anthropic / openai / openrouter
LODESTONE_MODEL_NAME=llama3.2
```

---

## 10. What's done vs. what's next

**Done (v0.2):**
- Agent-first workspace, 4 agents sharing one brain
- Knowledge-graph + vector brain, fused recall
- BYO-model layer (6 backends incl. offline mock), running live on Ollama
- Auto-recall + auto-learn
- Connectors (files/notes/gmail/notion/gdrive) that build the graph
- Folder picker; chat UI with visible tool trace
- 5 passing tests; runs fully offline with zero keys

**Next (tomorrow's list):**
1. **Continuous background sync** — auto re-index sources; true "set and forget."
2. **Gmail "draft my email" hero demo** — the flagship Turnstone flow.
3. **More connectors** — iMessage, browser history, Linear.
4. Single-file ingest in the picker; a bigger local model for sharper answers.
5. Later: Tauri desktop shell (menubar app) wrapping this same engine.

**Honest limitations right now:**
- `llama3.2` is only 3B — answers are decent, not brilliant. Bigger model = better.
- The `subscription` model path is a gateway slot, not a full reverse-engineering
  of each vendor's private auth.
- Connectors run on a manual "sync" click (continuous sync is next).

---

## 11. Mini-glossary (for the "from basics" part)

- **Embedding / vector** — text turned into numbers that capture meaning; lets us
  find things by *meaning*, not exact words.
- **Cosine similarity** — a way to measure how close two vectors (meanings) are.
- **Knowledge graph** — a web of entities (nodes) and facts/relations (edges).
- **RAG (retrieval-augmented generation)** — fetch relevant context, then let the
  model answer using it. Our recall step is the "retrieval."
- **Tool / function calling** — the model can ask the app to run a function
  (e.g. search the brain) and use the result.
- **Agentic loop** — model → maybe call a tool → read result → repeat → answer.
- **MCP (Model Context Protocol)** — a standard for connecting tools to models;
  used in the earlier (scrapped) version, not the core of the current one.
- **Provider / backend** — a specific model service (Claude, OpenAI, Ollama…).
- **Connector** — code that pulls data from a source (Gmail, files…) into the brain.
- **Sidecar** — a bundled background process; how a future desktop app would ship
  this Python engine.

---

## 12. Timeline of what we did (session history)

1. Researched Turnstone; first (wrong) mental model = passive memory server.
2. Built v0.1: passive MCP context server. Ran it. User flagged it as wrong.
3. Re-researched deeply; corrected understanding to "agent workspace."
4. Rebuilt v0.2 agent-first: models → brain → agents → connectors → API → UI.
5. Committed + pushed to `TURNOVER`.
6. Installed Ollama; agents now reason on a free local model.
7. Fixed reasoning reliability with **auto-recall**.
8. Added **auto-learn** so talking grows the brain.
9. Made connectors build the graph (fast bulk extraction).
10. Added a **folder picker**; fixed "no files found."
11. Wrote this document.

_Every commit is on `main` at https://github.com/suryansh2846code/TURNOVER._
