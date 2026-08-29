# Lodestone — Concepts & Learning Guide

> The companion to [`PROJECT.md`](PROJECT.md). That doc explains *what we built
> and why*. This doc explains the *ideas underneath it* — embeddings, vector
> search, semantic search, and the knowledge graph — from scratch, in the order
> we actually learned them. If those words are new to you, read this.

---

## 1. The mental model of the whole app

The LLM (Claude, GPT, a local model…) is a **stateless reasoning engine**. It
knows nothing about you. Lodestone's entire job is to **retrieve the right slice
of your local knowledge and put it into the prompt** at the right moment, so the
model *acts like* it already knows you.

This pattern has a name: **RAG — Retrieval-Augmented Generation.**
"Retrieval" = find the relevant context. "Generation" = the model answers using it.

Everything below is how we do the retrieval well.

---

## 2. Two phases

### Phase 1 — Building the brain (ahead of time, local, private)
Runs when you sync a connector or chat. Nothing leaves your machine.

```
your data (files, notes, chat, email…)
  → CHUNK    split into ~1,200-char paragraph-aware pieces
  → EMBED    turn each piece into a vector (numbers capturing meaning)
  → EXTRACT  pull out entities + facts → the knowledge graph
  → STORE    save text + vector + graph into local SQLite
```

### Phase 2 — Answering (query time)
```
1. You ask a question
2. RECALL  search the brain (vectors + graph) for the most relevant pieces
3. PROMPT  build [agent identity] + [recalled context] + [your question]
4. SEND    to the LLM (local Ollama, or a cloud model if you choose)
5. TOOLS   (optional) model calls a tool → result feeds back → repeat
6. ANSWER  returned; then AUTO-LEARN saves any new facts you revealed
```

The prompt the model receives is literally your question wrapped in facts pulled
from your own brain. That's the "never explain yourself again" trick.

---

## 3. Chunking — why we split text

A whole document is a bad unit to search: too big, and a match doesn't tell you
*where* the answer is. So we split into ~1,200-character, paragraph-aware pieces
with slight overlap (so meaning isn't cut mid-sentence). Each piece becomes one
independently-retrievable "memory" — small enough to be precise, big enough to
be meaningful. Code: `core/chunk.py`.

---

## 4. Embeddings — turning meaning into numbers

An **embedding** is a fixed-length list of numbers (a **vector**) that represents
the *meaning* of a piece of text. Our default vector has 256 numbers; real models
use 384–3072.

The magic property:

> **Text with similar meaning gets vectors that point in similar directions.**

Picture each vector as an arrow in space. "Cloudflare Workers" and "serverless
backend" point almost the same way; "pasta dinner" points off elsewhere. (Real
models use hundreds of dimensions — impossible to picture, same math as 2-D
arrows.)

### Who decides the meaning? (the key question)
**Not a person. Not a dictionary. A neural network — and it *learned* meaning by
reading enormous amounts of human text.**

- **Principle (distributional hypothesis):** *"you know a word by the company it
  keeps."* Meaning isn't defined anywhere; it emerges from usage. "Feline" ≈
  "cat" because across billions of sentences they appear in the same contexts.
- **Mechanism:** an embedding model is a giant math function with millions of
  tunable knobs (**weights**). Text in → numbers out. Nobody sets the knobs by
  hand.
- **Training (contrastive learning):** the model is shown pairs — "these two
  sentences mean the same, make their vectors close" / "these are unrelated, push
  them apart" — guesses, checks how wrong it was, and nudges its knobs. Repeat
  billions of times until meaning-similar text lands in the same region of space.
- **So who determines meaning?** Humanity, indirectly. The model distills meaning
  from patterns in text written by millions of people. The model is the machine;
  human language is the source of truth.

### Important honesty about our default
Our default `hash` embedder does **not** understand meaning — it just hashes
words into number-slots (fast, offline, zero-setup). Proof from our own test:

| Two sentences | Meaning | `hash` score | A real model would say |
|---|---|---|---|
| "cat sat on the **mat**" vs "**feline rested on the rug**" | same | 0.27 ❌ | high ✅ |
| "deploy my **worker**" vs "publish a **cloudflare function**" | same | −0.11 ❌ | high ✅ |
| "cat sat on the **mat**" vs "cat sat on the **hat**" | different | 0.90 ❌ | low ✅ |

The `hash` embedder sees "mat ≈ hat" (similar letters) and misses "cat ≈ feline"
(same meaning, different letters). A **trained** model (`local` / OpenAI) is the
thing that actually captures meaning. Switch with one env var:
`LODESTONE_EMBEDDING_PROVIDER=local`. Code: `core/embeddings.py` (pluggable:
hash | local | openai | gemini).

---

## 5. Cosine similarity — measuring "closeness"

To rank results we measure the **angle** between the query's arrow and each
stored arrow:

- same direction → similarity ≈ **1.0** (very relevant)
- perpendicular → **0.0** (unrelated)
- opposite → **−1.0**

In code it's a dot product of normalized vectors (`query_vec @ stored_vec`). One
number per stored item; sort descending = ranked search results.

---

## 6. Vector "databases" — what they actually are

A vector database is just **a store that (1) holds vectors and (2) quickly finds
the nearest ones to a query vector.** That's the whole job.

- **Keyword search** finds rows *containing a word*. Fails when words differ.
- **Vector search** finds rows *with similar meaning*. Works with zero shared words.

The hard part a real vector DB optimizes: with millions of vectors, comparing
against every one is slow, so they use **ANN** (approximate nearest neighbor)
indexes to find close ones without checking all.

| Option | What it is | We use? |
|---|---|---|
| **Ours** | vectors as BLOBs in SQLite, compared in NumPy | ✅ |
| pgvector | Postgres vector column + index | no |
| sqlite-vec | SQLite vector-search extension | not yet (natural future upgrade) |
| Chroma / Pinecone / Weaviate / FAISS | dedicated vector DBs / ANN libraries | no |

**Why ours is fine now:** at a few thousand–tens of thousands of memories,
"compare against all" in NumPy takes milliseconds. You don't need an ANN index
until ~hundreds of thousands. Because the embedding layer is pluggable, adding
`sqlite-vec` later won't touch the rest of the app.

---

## 7. Semantic search — putting it together

**"Semantic" = by meaning.** Semantic search = finding results by what they
*mean*, not by exact keywords.

```
1. Embed your query into a vector (its meaning)
2. Compare it to every stored vector by cosine similarity
3. Return the closest → the most meaning-relevant memories
```

That's the recall step. When "what infra runs my bot?" found the Cloudflare
memory despite no shared words — that was semantic search working. It's only as
good as the embedding model behind it (see §4).

---

## 8. Why ALSO a knowledge graph? (vectors aren't enough)

Vector search is great at *fuzzy, what's-related* retrieval, but it has real
weaknesses. A **knowledge graph** — explicit **entities** (nodes) and **facts /
relationships** (edges) — fixes them. We use **both** (this is often called
"GraphRAG").

### What pure vector search is bad at
1. **No structure** — it returns similar text blobs, not a consolidated answer.
   "List every tool project X uses" is unreliable when the tools are scattered
   across 20 chunks.
2. **No relationships** — it can't traverse "X uses Y, and Y depends on Z."
3. **Redundancy** — one entity mentioned in 20 chunks returns 20 near-duplicates
   instead of one clean view.
4. **No notion of importance** — every chunk is equal; nothing says "this project
   is central, mentioned 42 times."

### What the graph adds
1. **Entity-centric answers** — one consolidated node per thing:
   `WhatsApp Agent → built_on → {Cloudflare Workers, Groq, Meta API, Sheets}`.
2. **Deduplicated, consolidated facts** — all facts about an entity in one place,
   with a **mention count** = a cheap importance signal.
3. **Connections across documents** — facts from different files link to the same
   entity, enabling multi-hop understanding.
4. **A clean, structured block the LLM loves** — recall injects a tidy
   "KNOWN ENTITIES & FACTS" list, not just raw prose.

### How we fuse them (best of both)
`Brain.recall(query)` returns ONE block:
```
KNOWN ENTITIES & FACTS:      ← from the graph (precise, structured, consolidated)
 • WhatsApp Agent: built on Cloudflare Workers, Groq, Meta API, Sheets
RELEVANT MEMORIES:           ← from vector search (fuzzy coverage, exact wording)
 [notes] The WhatsApp agent is a multi-tenant assistant ...
```
Vectors give **coverage** (find relevant text even with vague queries); the graph
gives **precision + structure** (a clean, deduped view of the key entities).

### Honest clarification
Our "graph" is **not** a dedicated graph database (like Neo4j). It's graph-shaped
tables in the same SQLite file — `entities` (nodes) and `relations` (edges). We
build the *knowledge graph data structure*; we just store it in SQLite. Simpler,
local, one file. Code: `brain/graph.py`, `brain/extract.py`.

### Quality matters (the polish angle)
A graph full of junk ("Date", "JSON", "ADR") is worse than none — the LLM reads
noise. So extraction is **precision-first**: only real proper nouns, only prose
(not source code) feeds the graph. We took the graph from 3,465 junk entities
down to ~436 clean ones. See the extraction filter in `brain/extract.py`.

---

## 9. Where the data lives (database choice)

- **SQLite** — one local file, embedded, no server. `~/Library/Lodestone/`.
  - `lodestone.db` → `memories` (text + vector BLOB), `entities`, `relations`.
  - `agents.db` → each agent's chat history.
- **Why SQLite:** local-first (the product thesis), zero-config, portable (copy
  one file to back up), fast enough for tens of thousands of memories, and it
  ships cleanly inside a future desktop app.
- **Turnstone's DB:** not publicly disclosed (closed source). Almost certainly
  SQLite too (standard for local Mac apps), likely with a vector extension like
  `sqlite-vec`. Beware: web searches surface `.turnstone.db` from the *unrelated*
  `turnstonelabs/turnstone` OSS project — not myturnstone.ai.

---

## 10. How Turnstone (and therefore Lodestone) runs — no servers

- A **downloadable local app**; the brain, indexing and storage all happen on the
  user's machine.
- **No deployment / no GPU servers doing the AI work.** (A tiny backend may exist
  for the website, accounts and updates — never for your data.)
- **Bring your own model**, four ways: API key · existing subscription · OpenRouter
  · free local models.
- **The one place data leaves your machine:** *inference*. If you pick a cloud
  model, the prompt (including injected brain context) goes to that provider at
  query time. A **local model keeps everything on-device.** Lodestone defaults to
  a local model, so out-of-the-box nothing leaves your machine.

Cost to run: ~nothing. The user's machine and the user's chosen model do the work.

---

## 11. Glossary

- **RAG** — retrieve relevant context, then let the model answer using it.
- **Embedding / vector** — text turned into numbers that capture meaning.
- **Weights** — the millions of tunable numbers inside a model, set by training.
- **Contrastive learning** — training that pulls same-meaning vectors together and
  pushes different ones apart.
- **Cosine similarity** — closeness of two vectors by the angle between them.
- **ANN** — approximate nearest neighbor; fast "find closest vectors" at scale.
- **Semantic search** — search by meaning, not keywords.
- **Knowledge graph** — entities (nodes) + facts (edges).
- **GraphRAG** — RAG that combines vector search with a knowledge graph.
- **Chunk** — a small, independently-retrievable piece of a document.
