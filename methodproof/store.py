"""SQLite store — sessions, events, graph relationships."""

import json
import sqlite3
import time
import uuid
from typing import Any

from methodproof import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    watch_dir TEXT NOT NULL,
    created_at REAL NOT NULL,
    completed_at REAL,
    total_events INTEGER DEFAULT 0,
    synced INTEGER DEFAULT 0,
    remote_id TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    duration_ms REAL DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, timestamp);
CREATE TABLE IF NOT EXISTS next_chain (
    from_id TEXT NOT NULL, to_id TEXT NOT NULL, gap_ms REAL,
    PRIMARY KEY (from_id, to_id)
);
CREATE TABLE IF NOT EXISTS causal_links (
    source_id TEXT NOT NULL, target_id TEXT NOT NULL,
    type TEXT NOT NULL, confidence REAL DEFAULT 1.0,
    PRIMARY KEY (source_id, target_id, type)
);
CREATE TABLE IF NOT EXISTS resources (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, identifier TEXT NOT NULL,
    UNIQUE(type, identifier)
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY, path TEXT NOT NULL, type TEXT DEFAULT 'file',
    size_bytes INTEGER DEFAULT 0
);
"""

_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db() -> None:
    config.ensure_dirs()
    _db().executescript(_SCHEMA)


def create_session(session_id: str, watch_dir: str) -> None:
    _db().execute(
        "INSERT INTO sessions (id, watch_dir, created_at) VALUES (?, ?, ?)",
        (session_id, watch_dir, time.time()),
    )
    _db().commit()


def complete_session(session_id: str) -> None:
    db = _db()
    count = db.execute(
        "SELECT count(*) FROM events WHERE session_id = ?", (session_id,),
    ).fetchone()[0]
    db.execute(
        "UPDATE sessions SET completed_at = ?, total_events = ? WHERE id = ?",
        (time.time(), count, session_id),
    )
    db.commit()


def insert_events(session_id: str, events: list[dict[str, Any]]) -> None:
    db = _db()
    db.executemany(
        "INSERT OR IGNORE INTO events (id, session_id, type, timestamp, duration_ms, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(e["id"], session_id, e["type"], e["timestamp"],
          e.get("duration_ms", 0), json.dumps(e.get("metadata", {})))
         for e in events],
    )
    db.commit()


def get_session(session_id: str) -> dict[str, Any] | None:
    row = _db().execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_sessions() -> list[dict[str, Any]]:
    rows = _db().execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_events(session_id: str) -> list[dict[str, Any]]:
    rows = _db().execute(
        "SELECT * FROM events WHERE session_id = ? ORDER BY timestamp",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_graph(session_id: str) -> dict[str, Any]:
    """Build GraphResponse-compatible dict from SQLite."""
    events = get_events(session_id)
    nodes = [{"id": e["id"], "type": "Action", "label": e["type"],
              "properties": {"timestamp": e["timestamp"], "duration_ms": e["duration_ms"],
                             "metadata": json.loads(e["metadata"])}}
             for e in events]

    edges = []
    for row in _db().execute(
        "SELECT * FROM next_chain WHERE from_id IN "
        "(SELECT id FROM events WHERE session_id = ?)", (session_id,),
    ).fetchall():
        edges.append({"source": row["from_id"], "target": row["to_id"],
                       "type": "NEXT", "properties": {"gap_ms": row["gap_ms"]}})
    for row in _db().execute(
        "SELECT * FROM causal_links WHERE source_id IN "
        "(SELECT id FROM events WHERE session_id = ?)", (session_id,),
    ).fetchall():
        edges.append({"source": row["source_id"], "target": row["target_id"],
                       "type": row["type"], "properties": {"confidence": row["confidence"]}})
    return {"nodes": nodes, "edges": edges}


def mark_synced(session_id: str, remote_id: str) -> None:
    _db().execute(
        "UPDATE sessions SET synced = 1, remote_id = ? WHERE id = ?",
        (remote_id, session_id),
    )
    _db().commit()
