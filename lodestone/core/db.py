"""SQLite schema and connection handling."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id                  TEXT PRIMARY KEY,
    text                TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'manual',
    kind                TEXT NOT NULL DEFAULT 'note',
    title               TEXT,
    uri                 TEXT,
    tags                TEXT NOT NULL DEFAULT '[]',
    metadata            TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    embedding           BLOB,
    embed_dim           INTEGER,
    embed_model         TEXT,
    content_hash        TEXT,
    event_date          TEXT,         -- real date of the item (email/event), ISO YYYY-MM-DD
    graphed             INTEGER NOT NULL DEFAULT 0,   -- processed by the graph enricher yet?

    -- Brain v1.5 fields
    memory_type         TEXT NOT NULL DEFAULT 'semantic',  -- episodic|semantic|preference|procedural|contextual|commitment|observation
    source_id           TEXT,         -- external identifier (message id, file hash, etc.)
    event_time          TEXT,         -- full ISO datetime if known
    valid_from          TEXT,         -- when this fact became true
    valid_until         TEXT,         -- when this fact stopped being true (NULL if currently true)
    importance          REAL NOT NULL DEFAULT 0.5,  -- 0.0 to 1.0 importance score
    confidence          REAL NOT NULL DEFAULT 0.8,  -- 0.0 to 1.0 confidence score
    reinforcement_count INTEGER NOT NULL DEFAULT 0, -- times confirmed/reinforced
    last_reinforced_at  TEXT,         -- last time confirmation was observed
    last_accessed_at    TEXT,         -- last time returned in recall
    access_count        INTEGER NOT NULL DEFAULT 0, -- recall frequency
    status              TEXT NOT NULL DEFAULT 'active',  -- active|superseded|uncertain|disputed|expired|retracted
    extraction_method   TEXT DEFAULT 'direct',  -- direct|llm_inference|heuristic|user_statement
    supersedes_id       TEXT,         -- memory id this entry replaced
    evidence            TEXT          -- provenance snippet or reason
);

CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source);
CREATE INDEX IF NOT EXISTS idx_memories_uri ON memories(uri);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_chash ON memories(content_hash);

CREATE TABLE IF NOT EXISTS connector_state (
    connector  TEXT PRIMARY KEY,
    cursor     TEXT,
    last_sync  TEXT,
    status     TEXT,
    detail     TEXT
);

-- Knowledge graph: entities and the facts/relations that connect them.
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    norm        TEXT NOT NULL,          -- lowercased key for dedup
    type        TEXT NOT NULL DEFAULT 'thing',  -- person|project|org|tool|place|topic|thing
    summary     TEXT NOT NULL DEFAULT '',
    mentions    INTEGER NOT NULL DEFAULT 1,
    embedding   BLOB,
    embed_dim   INTEGER,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    -- Brain v1.5 entity fields
    aliases     TEXT NOT NULL DEFAULT '[]',
    confidence  REAL NOT NULL DEFAULT 0.8,
    importance  REAL NOT NULL DEFAULT 0.5,
    source      TEXT DEFAULT 'direct'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_norm ON entities(norm);

CREATE TABLE IF NOT EXISTS relations (
    id          TEXT PRIMARY KEY,
    subject_id  TEXT NOT NULL,
    predicate   TEXT NOT NULL,
    object_id   TEXT,
    fact        TEXT NOT NULL,          -- human-readable statement
    source_mem  TEXT,                   -- originating memory id
    created_at  TEXT NOT NULL,
    -- Brain v1.5 relation fields
    confidence  REAL NOT NULL DEFAULT 0.8,
    source      TEXT DEFAULT 'direct',
    valid_from  TEXT,
    valid_until TEXT
);
CREATE INDEX IF NOT EXISTS idx_rel_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_rel_object ON relations(object_id);

-- Open Loops: unfinished business, commitments, pending decisions
CREATE TABLE IF NOT EXISTS open_loops (
    id               TEXT PRIMARY KEY,
    description      TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'open',  -- open|waiting|blocked|completed|cancelled|stale
    priority         TEXT NOT NULL DEFAULT 'medium',  -- low|medium|high|urgent
    confidence       REAL NOT NULL DEFAULT 0.8,
    due_at           TEXT,
    source           TEXT NOT NULL DEFAULT 'manual',
    related_entities TEXT NOT NULL DEFAULT '[]',
    related_project  TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    completed_at     TEXT,
    metadata         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_open_loops_status ON open_loops(status);
CREATE INDEX IF NOT EXISTS idx_open_loops_due ON open_loops(due_at);

-- key/value store for migration version stamps (embedder, extractor, schema)
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    # wait up to 5s for a lock instead of failing instantly with "database is
    # locked" — the scheduler thread and request handlers share this connection.
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for existing databases to Brain v1.5."""
    # 1. memories columns
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(memories)")}
    if "event_date" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN event_date TEXT")
    if "graphed" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN graphed INTEGER NOT NULL DEFAULT 0")
    if "memory_type" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'semantic'")
    if "source_id" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN source_id TEXT")
    if "event_time" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN event_time TEXT")
    if "valid_from" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN valid_from TEXT")
    if "valid_until" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN valid_until TEXT")
    if "importance" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN importance REAL NOT NULL DEFAULT 0.5")
    if "confidence" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN confidence REAL NOT NULL DEFAULT 0.8")
    if "reinforcement_count" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN reinforcement_count INTEGER NOT NULL DEFAULT 0")
    if "last_reinforced_at" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN last_reinforced_at TEXT")
    if "last_accessed_at" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN last_accessed_at TEXT")
    if "access_count" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0")
    if "status" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if "extraction_method" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN extraction_method TEXT DEFAULT 'direct'")
    if "supersedes_id" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN supersedes_id TEXT")
    if "evidence" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN evidence TEXT")

    # 2. entities columns
    ecols = {r["name"] for r in conn.execute("PRAGMA table_info(entities)")}
    if "aliases" not in ecols:
        conn.execute("ALTER TABLE entities ADD COLUMN aliases TEXT NOT NULL DEFAULT '[]'")
    if "confidence" not in ecols:
        conn.execute("ALTER TABLE entities ADD COLUMN confidence REAL NOT NULL DEFAULT 0.8")
    if "importance" not in ecols:
        conn.execute("ALTER TABLE entities ADD COLUMN importance REAL NOT NULL DEFAULT 0.5")
    if "source" not in ecols:
        conn.execute("ALTER TABLE entities ADD COLUMN source TEXT DEFAULT 'direct'")

    # 3. relations columns
    rcols = {r["name"] for r in conn.execute("PRAGMA table_info(relations)")}
    if "confidence" not in rcols:
        conn.execute("ALTER TABLE relations ADD COLUMN confidence REAL NOT NULL DEFAULT 0.8")
    if "source" not in rcols:
        conn.execute("ALTER TABLE relations ADD COLUMN source TEXT DEFAULT 'direct'")
    if "valid_from" not in rcols:
        conn.execute("ALTER TABLE relations ADD COLUMN valid_from TEXT")
    if "valid_until" not in rcols:
        conn.execute("ALTER TABLE relations ADD COLUMN valid_until TEXT")

    # 4. Indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_event_date ON memories(event_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_graphed ON memories(graphed)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_status ON memories(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(memory_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_importance ON memories(importance)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_open_loops_status ON open_loops(status)")

    conn.commit()
