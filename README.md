# ◆ Lodestone

**The local-first AI workspace where your agents already know you.**

Lodestone is an open competitor to [Turnstone](https://myturnstone.ai). Connect
your apps and folders; Lodestone turns them into a **continuously-updated
knowledge-graph brain** on your own machine. Then spin up specialized **agents**
— Inbox, Launch, Research, Personal — that all share that one brain and run on
**any model you already pay for**. Stop re-explaining yourself to AI.

- 🧠 **Knowledge-graph brain** — memories *and* an entity/relation graph, built locally, shared by every agent.
- 🤖 **Four agents, one brain** — Inbox · Launch · Research · Personal, each domain-scoped, each remembering its own work.
- 🔌 **Bring your own model** — subscription gateway · Claude · OpenAI · OpenRouter · Ollama. Swap freely.
- 🛠️ **Agents that act** — tool-using loop: search the brain, search the web, pull live Gmail, remember new facts.
- 🔒 **Local-first** — everything in `~/Library/Lodestone`, no cloud copy, no telemetry.
- ⚡ **Runs day one** — offline `mock` model + `hash` embeddings mean zero keys required to try it.

> 📖 **New here? Read [`docs/PROJECT.md`](docs/PROJECT.md)** — a from-basics
> explainer of what this is, how every part works, and why each decision was made.

---

## Architecture

```
   ┌─────────── Workspace (web) ───────────┐
   │  Agent tabs   Chat + tool trace   Brain│
   └───────────────────┬────────────────────┘
                        │  FastAPI
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   Agent runtime   Model providers    Brain
   (tool loop)     (BYO: claude/      ├─ vector memories (SQLite)
   Inbox/Launch/   openai/openrouter/ └─ knowledge graph (entities+facts)
   Research/       ollama/subscription       ▲
   Personal)              │                   │ ingest + extract
        └── tools ─────────┘         Connectors: files · notes · gmail
                                     notion · gdrive (+ imessage/linear/…)
```

Agents are the core primitive. Each runs a **model + tool-use loop**: the model
decides to call tools (`search_brain`, `web_search`, `gmail_search`, `remember`),
Lodestone executes them against the shared brain and live connectors, and the
model answers — already knowing you.

## Install

```bash
uv venv && uv pip install -e .          # core, runs offline with zero keys
uv pip install -e ".[all]"              # + real embeddings & all connector SDKs
```

## Quickstart

```bash
lodestone serve                          # workspace at http://127.0.0.1:8787
lodestone agents                         # list Inbox/Launch/Research/Personal
lodestone ingest --text "I build for Indian SMBs on Cloudflare Workers."
lodestone chat research "what do I build?"
lodestone stats                          # brain + knowledge-graph stats
lodestone providers                      # model backends & readiness
```

## Bring your own model

Set `LODESTONE_MODEL_PROVIDER` (and the matching key) in `.env`:

| provider | how | key |
|----------|-----|-----|
| `mock` | offline, deterministic | none (default) |
| `anthropic` | Claude Messages API | `ANTHROPIC_API_KEY` |
| `openai` | GPT | `OPENAI_API_KEY` |
| `openrouter` | hundreds of models | `OPENROUTER_API_KEY` |
| `ollama` | free local models | none (Ollama on :11434) |
| `subscription` | your paid ChatGPT/Claude/Cursor session via a local OpenAI-compatible gateway | `LODESTONE_SUBSCRIPTION_BASE_URL` |

> The `subscription` path is the hard, ToS-sensitive route Turnstone advertises.
> Lodestone treats it as a pluggable gateway (point it at a local subscription
> proxy) rather than reverse-engineering each vendor's private auth.

## The brain

Ingestion writes to **both** a vector store (recallable chunks) and a
**knowledge graph** (entities + facts, extracted by the LLM when available, with
an offline heuristic fallback). Recall fuses both into one injectable context
block, so agents start already knowing your people, projects and preferences.

## Connectors (read-only)

`files`, `notes` work with no setup. `gmail`, `gdrive` need a Google OAuth
Desktop client (`GOOGLE_CLIENT_SECRETS`); `notion` needs `NOTION_TOKEN`.

## Roadmap

- [ ] iMessage · browser-history · Linear · Granola connectors (match Turnstone's set)
- [ ] Continuous background auto-indexing (watch folders/inbox)
- [ ] Streaming chat + inline tool approval (LLM-judged writes)
- [ ] Custom user-defined agents
- [ ] Tauri desktop shell (menubar app) wrapping this engine

## License

Apache-2.0.
