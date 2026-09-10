"""Tests for Brain v1.5 Database Migration, Failure Recovery, and Secret Protection."""
import sqlite3
import tempfile
import pytest

from lodestone.brain import Brain
from lodestone.core.store import MemoryStore


OLD_V1_SCHEMA = """
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
    content_hash TEXT
);
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    norm        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'thing',
    summary     TEXT NOT NULL DEFAULT '',
    mentions    INTEGER NOT NULL DEFAULT 1,
    embedding   BLOB,
    embed_dim   INTEGER,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relations (
    id          TEXT PRIMARY KEY,
    subject_id  TEXT NOT NULL,
    predicate   TEXT NOT NULL,
    object_id   TEXT,
    fact        TEXT NOT NULL,
    source_mem  TEXT,
    created_at  TEXT NOT NULL
);
"""


def test_migration_from_v1_database():
    db_path = tempfile.mktemp(suffix=".db")
    # 1. Create a database with the old schema
    conn = sqlite3.connect(db_path)
    conn.executescript(OLD_V1_SCHEMA)
    conn.execute(
        "INSERT INTO memories (id, text, source, kind, title, uri, tags, metadata, created_at, updated_at, content_hash) "
        "VALUES ('old-1', 'Legacy memory before upgrade', 'manual', 'note', 'Old Title', 'file://old', '[]', '{}', '2025-01-01', '2025-01-01', 'hash-1')"
    )
    conn.commit()
    conn.close()

    # 2. Open with MemoryStore (triggers _migrate)
    store = MemoryStore(db_path=db_path)

    # 3. Verify that old memory was preserved and upgraded with default v1.5 columns!
    old_mem = store.get("old-1")
    assert old_mem is not None
    assert old_mem.text == "Legacy memory before upgrade"
    assert old_mem.memory_type == "semantic"
    assert old_mem.status == "active"
    assert old_mem.confidence == 0.8
    assert old_mem.importance == 0.5
    assert old_mem.reinforcement_count == 0

    # 4. Verify that new v1.5 operations work on the migrated database
    store.add("New v1.5 memory", memory_type="preference", importance=0.9)
    assert store.count() == 2


def test_corrupted_metadata_and_missing_vectors_tolerance(tmp_path):
    store = MemoryStore(db_path=tmp_path / "corrupt.db")
    # Insert memory without embedding
    store._conn.execute(
        "INSERT INTO memories (id, text, source, kind, title, uri, tags, metadata, created_at, updated_at, content_hash, memory_type, status, importance, confidence) "
        "VALUES ('no-vec', 'Lexical only memory with no vector', 'manual', 'note', 'No Vector', NULL, '[]', 'INVALID_JSON', '2026-01-01', '2026-01-01', 'hash-no-vec', 'semantic', 'active', 0.5, 0.8)"
    )
    store._conn.commit()

    # Store search should not crash on missing vector or corrupted metadata
    hits = store.search("Lexical only memory", limit=5)
    assert any(h.memory.id == "no-vec" for h in hits)


def test_secret_redaction_on_ingest(tmp_path):
    brain = Brain(store=MemoryStore(db_path=tmp_path / "secrets.db"))

    # Ingest text containing API key and password
    res = brain.ingest("My OpenAI API key is sk-1234567890abcdef1234 and my password is secretpassword123")
    assert res["memories"] == 1

    # Verify that secrets were redacted before storage
    mems = brain.store.list()
    assert len(mems) == 1
    stored_text = mems[0].text
    assert "sk-1234567890abcdef1234" not in stored_text
    assert "secretpassword123" not in stored_text
    assert "[REDACTED_KEY]" in stored_text or "[REDACTED" in stored_text
