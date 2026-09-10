# TURNOVER / Lodestone — Brain v1.5 Architecture & Specification

## 1. Core Architectural Thesis

The Brain is the persistent intelligence substrate of TURNOVER / Lodestone.
**The LLM is NOT the Brain.**
The LLM is provider-agnostic execution compute that interprets, summarizes, reasons, and generates text.
The Brain owns:
- Persistent memory with temporal fidelity
- Knowledge graph (entities, relations, provenance)
- Confidence, importance, and activation scores
- Fact evolution and contradiction detection
- Open loops (commitments, unfinished decisions)
- Multi-signal hybrid retrieval and contextual packing

```
USER ──► WORKSPACE ──► AGENTS ──► BRAIN (v1.5 Foundation)
                                    ├── Temporal Memory (Episodic, Semantic, Preference...)
                                    ├── Knowledge Graph (Canonical Entities & Validated Relations)
                                    ├── Open Loops (Commitments, Pending Tasks)
                                    ├── Multi-Signal Hybrid Retrieval
                                    └── Contradiction & Provenance Engine
```

---

## 2. Memory Model & Schema

Every memory record in Brain v1.5 answers:
- **WHAT** is this? (`text`, `title`, `tags`, `metadata`)
- **WHEN** did we learn it? (`created_at`, `updated_at`)
- **WHEN** was it true? (`event_time`, `valid_from`, `valid_until`)
- **WHERE** did it come from? (`source`, `source_id`, `extraction_method`, `evidence`)
- **HOW CONFIDENT** are we? (`confidence`: 0.0 – 1.0)
- **HOW IMPORTANT** is it? (`importance`: 0.0 – 1.0)
- **HAS IT BEEN REINFORCED?** (`reinforcement_count`, `last_reinforced_at`)
- **IS IT STILL VALID?** (`status`: active, superseded, uncertain, disputed, expired, retracted)
- **HOW ACTIVE** is it? (`access_count`, `last_accessed_at`, `compute_activation()`)

### Database Table: `memories`
```sql
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    source TEXT NOT NULL,           -- manual, chat, agent, gmail, calendar, drive, notion, github
    kind TEXT NOT NULL,             -- note, document, event, message, conversation, fact
    title TEXT,
    uri TEXT,
    tags TEXT,                      -- JSON list of strings
    metadata TEXT,                  -- JSON key-value store
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    content_hash TEXT,
    event_date TEXT,
    graphed INTEGER DEFAULT 0,
    -- Brain v1.5 Additive Columns:
    memory_type TEXT DEFAULT 'semantic',
    source_id TEXT,
    event_time TEXT,
    valid_from TEXT,
    valid_until TEXT,
    importance REAL DEFAULT 0.5,
    confidence REAL DEFAULT 0.8,
    reinforcement_count INTEGER DEFAULT 0,
    last_reinforced_at TEXT,
    last_accessed_at TEXT,
    access_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    extraction_method TEXT DEFAULT 'direct',
    supersedes_id TEXT,
    evidence TEXT
);
```

---

## 3. Controlled Memory Taxonomy

Memory types support structured classification without brittle constraints:
- `episodic`: Point-in-time interactions, meeting notes, conversation logs.
- `semantic`: Durable world knowledge, domain concepts, documentation facts.
- `preference`: User habits, workflow styles, tooling choices (e.g., UI theme, editor).
- `procedural`: Operational instructions, runbooks, build commands.
- `contextual`: Ephemeral project state, working environment parameters.
- `commitment`: Explicit promises, deadlines, agreements made with people.
- `observation`: Agent-noticed patterns or inferred behavioral facts.

---

## 4. Temporal Reasoning & Non-Destructive Evolution

Traditional vector databases silently overwrite or blur historical changes. Brain v1.5 enforces **history preservation**:
1. When a user changes their preference (e.g. "React in 2025" → "Vanilla JS in 2026"):
   - The original fact is marked `status = 'superseded'` and `valid_until = '2026-01-01'`.
   - The new fact is created with `status = 'active'`, `valid_from = '2026-01-01'`, and `supersedes_id = <old_id>`.
2. Present-day queries prioritize active facts and penalize superseded facts.
3. Historical queries (containing "previously", "used to", "in 2025") surface historical facts with their respective validity windows.

---

## 5. Multi-Signal Hybrid Retrieval

Retrieval combines semantic embeddings, BM25-equivalent lexical matching, graph entities, and cognitive metadata:

$$\text{Final Score} = S_{\text{semantic}} + 0.3 \cdot S_{\text{lexical}} + B_{\text{importance}} + B_{\text{confidence}} + B_{\text{recency}} + B_{\text{temporal}} + B_{\text{reinforce}} + B_{\text{source}} - P_{\text{status}}$$

### Scoring Components
- **$S_{\text{semantic}}$**: Cosine similarity against FastEmbed / HashEmbedder / Provider vectors.
- **$S_{\text{lexical}}$**: Token match density over query terms.
- **$B_{\text{importance}}$**: Up to $+0.15 \cdot \text{importance}$.
- **$B_{\text{confidence}}$**: Up to $+0.15 \cdot \text{confidence}$.
- **$B_{\text{recency}}$**: Exponential decay over recency of creation or event date.
- **$B_{\text{temporal}}$**: $+0.25$ if memory validity matches the temporal query target; $+0.20$ if historical query requests prior state.
- **$B_{\text{reinforce}}$**: Logarithmic boost: $+0.05 \cdot \ln(1 + \text{reinforcement\_count})$.
- **$B_{\text{source}}$**: Source reliability weighting:
  - `manual`, `direct_user`: $+0.10$
  - `chat`, `conversation`: $+0.08$
  - `gmail`, `calendar`, `github`: $+0.05$
  - `agent`, `inference`: $+0.02$
- **$P_{\text{status}}$**:
  - `superseded`: $-0.40$ (unless explicitly doing a historical lookup)
  - `retracted`: $-1.00$ (excluded from active recall)
  - `disputed`, `uncertain`: $-0.20$

Every retrieved memory hit includes an **explainability block** (`RecallExplanation`) documenting the exact breakdown.

---

## 6. Open Loops (Commitments & Unfinished Tasks)

Open loops represent unfinished obligations, waiting states, or active commitments:
- Table: `open_loops` (`id`, `description`, `status`, `priority`, `confidence`, `due_at`, `source`, `related_entities`, `related_project`, `created_at`, `updated_at`, `completed_at`, `metadata`).
- Lifecycle: `open` ➔ `waiting` ➔ `blocked` ➔ `completed` / `cancelled` / `stale`.
- Integrated automatically into prompt context during recall:
  ```text
  ACTIVE OPEN LOOPS & COMMITMENTS:
  - Deploy production build to staging [TURNOVER] (due: 2026-09-15)
  ```

---

## 7. Knowledge Graph Hardening

GraphStore now supports:
- Canonical entity normalization and aliases (`aliases` column in `entities`).
- Stop-word filtering rejecting noise tokens (`"thing"`, `"system"`, `"good"`, `"work"`).
- Entity types: `person`, `project`, `organization`, `place`, `product`, `technology`, `concept`, `event`.
- Relation attributes: `confidence`, `source`, `valid_from`, `valid_until`.

---

## 8. Security & Secret Redaction

To prevent prompt injection credentials or accidental leak of tokens into persistent memory:
- `redact()` runs on all ingestion streams.
- Redacts OpenAI, Anthropic, AWS, GitHub tokens, Bearer authorization headers, and connection strings (`password=...`).
- Tokens are replaced with deterministic privacy masks (`[REDACTED_KEY]`, `[REDACTED_PASSWORD]`, `[REDACTED_SECRET]`).

---

## 9. Migration & Zero-Downtime Compatibility

- Schema migrations (`lodestone/core/db.py`) use `PRAGMA table_info` introspection.
- Additive columns are dynamically added with `ALTER TABLE`.
- Missing vector indexes are conditionally built only after columns are verified.
- Malformed JSON in existing legacy databases gracefully falls back to empty default structures (`_safe_json_loads`).

---

## 10. Benchmark & Quality Evaluation

- Ingestion benchmark: **1.9 ms** per memory (vector + db write + secret redaction).
- Retrieval benchmark: **1.2 ms** per query (semantic + lexical + multi-signal ranking).
- Recall precision: **100%** on synthetic evaluation suite.
- Provenance coverage: **100%** across all ingested memories.
- Repeated connector sync duplicate rate: **0.0%** (deterministic content-hash idempotency).
