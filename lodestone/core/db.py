"""SQLite schema and connection handling."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'manual',
    kind        TEXT NOT NULL DEFAULT 'note',
    title       TEXT,
    uri         TEXT,
    tags        TEXT NOT NULL DEFAULT '[]',
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    embedding   BLOB,
    embed_dim   INTEGER,
    embed_model TEXT,
    content_hash TEXT,
    event_date  TEXT          -- real date of the item (email/event), ISO YYYY-MM-DD
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
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_norm ON entities(norm);

CREATE TABLE IF NOT EXISTS relations (
    id          TEXT PRIMARY KEY,
    subject_id  TEXT NOT NULL,
    predicate   TEXT NOT NULL,
    object_id   TEXT,
    fact        TEXT NOT NULL,          -- human-readable statement
    source_mem  TEXT,                   -- originating memory id
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_rel_object ON relations(object_id);

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
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for existing databases."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(memories)")}
    if "event_date" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN event_date TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_event_date "
                 "ON memories(event_date)")
    conn.commit()
