"""Canonical Brain database — the curated, source-backed model of the user.

Kept in a SEPARATE SQLite file (`brain.db`) from the raw source index
(`lodestone.db`). This is deliberate: thousands of emails never become
"memory" — only validated, evidence-backed claims land here. SQLite is the
only writable source of truth; the Markdown/JSON export is generated from it.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
-- People, projects, orgs, places, topics the user actually cares about.
CREATE TABLE IF NOT EXISTS entities (
    id             TEXT PRIMARY KEY,
    type           TEXT NOT NULL,               -- person|project|organization|place|topic
    canonical_name TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',  -- active|archived
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ent_type ON entities(type);

-- Stable keys that let us resolve "who is this" without guessing by name.
CREATE TABLE IF NOT EXISTS entity_identifiers (
    id               TEXT PRIMARY KEY,
    entity_id        TEXT NOT NULL,
    kind             TEXT NOT NULL,   -- email|gmail_contact_id|github_login|alias
    value_normalized TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(kind, value_normalized)
);
CREATE INDEX IF NOT EXISTS idx_ident_entity ON entity_identifiers(entity_id);

-- Versioned, evidence-backed facts. Append-only: we never UPDATE a claim's
-- truth in place — a change appends a new version and supersedes the old one.
CREATE TABLE IF NOT EXISTS claims (
    id                  TEXT PRIMARY KEY,
    entity_id           TEXT,                     -- null = user-level (About You)
    section             TEXT NOT NULL,            -- about_you|people|work
    type                TEXT NOT NULL,            -- preference|goal|role|project_status|decision|risk|next_step|...
    value_json          TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'current',  -- current|historical|open|resolved
    confidence          TEXT NOT NULL DEFAULT 'inferred', -- confirmed|inferred
    freshness           TEXT NOT NULL DEFAULT 'fresh',    -- fresh|aging|stale
    valid_from          TEXT,
    valid_to            TEXT,
    source_timestamp    TEXT,
    last_confirmed_at   TEXT,
    supersedes_claim_id TEXT,
    claim_key           TEXT,                     -- (entity,type,subject) grouping for supersession
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claim_entity ON claims(entity_id);
CREATE INDEX IF NOT EXISTS idx_claim_state ON claims(state);
CREATE INDEX IF NOT EXISTS idx_claim_key ON claims(claim_key);

-- Immutable timeline. Events are never superseded; they simply happened.
CREATE TABLE IF NOT EXISTS events (
    id               TEXT PRIMARY KEY,
    event_type       TEXT NOT NULL,   -- interaction|decision|commitment|milestone|change
    occurred_at      TEXT NOT NULL,   -- ISO date/datetime the thing happened
    summary          TEXT NOT NULL,
    entity_id        TEXT,
    source_timestamp TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_when ON events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_event_entity ON events(entity_id);

-- Every claim / event must retain where it came from.
CREATE TABLE IF NOT EXISTS evidence (
    id           TEXT PRIMARY KEY,
    claim_id     TEXT,
    event_id     TEXT,
    source_type  TEXT NOT NULL,       -- gmail|calendar|drive|file|chat|manual
    source_uri   TEXT,
    external_id  TEXT,
    excerpt      TEXT,
    excerpt_hash TEXT,
    captured_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_claim ON evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_evidence_event ON evidence(event_id);

-- Follow-ups / commitments (open loops with the outside world).
CREATE TABLE IF NOT EXISTS tasks (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    owner             TEXT NOT NULL DEFAULT 'user',  -- user|external_person
    state             TEXT NOT NULL DEFAULT 'open',  -- open|waiting|done|cancelled
    due_at            TEXT,
    entity_id         TEXT,
    source_timestamp  TEXT,
    last_confirmed_at TEXT,
    created_at        TEXT NOT NULL,
    UNIQUE(title, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_task_state ON tasks(state);

-- Review queue. NOTHING reaches canonical truth without passing through here
-- (auto-approved or human-approved). payload_json is a serialized Candidate.
CREATE TABLE IF NOT EXISTS candidates (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,       -- claim|event|task|identity
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|merged|needs_review
    reason       TEXT,
    payload_json TEXT NOT NULL,
    source_type  TEXT,
    source_uri   TEXT,
    created_at   TEXT NOT NULL,
    decided_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_cand_status ON candidates(status);

-- Held-out evaluation set for measuring recall quality before trusting curation.
CREATE TABLE IF NOT EXISTS evaluation_cases (
    id                  TEXT PRIMARY KEY,
    query               TEXT NOT NULL,
    expected_claim_ids  TEXT NOT NULL DEFAULT '[]',
    expected_entity_ids TEXT NOT NULL DEFAULT '[]',
    expected_source_ids TEXT NOT NULL DEFAULT '[]',
    freshness_expect    TEXT,
    created_at          TEXT NOT NULL
);

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
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
