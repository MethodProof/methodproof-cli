"""SQLite store — sessions, events, graph relationships."""

import json
import sqlite3
import time
import uuid
import zlib
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
    remote_id TEXT,
    repo_url TEXT,
    tags TEXT DEFAULT '[]',
    visibility TEXT DEFAULT 'private'
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
    id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, type TEXT DEFAULT 'file',
    size_bytes INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS action_resources (
    action_id TEXT NOT NULL, resource_id TEXT NOT NULL,
    relation_type TEXT NOT NULL, metadata TEXT DEFAULT '{}',
    PRIMARY KEY (action_id, resource_id, relation_type)
);
CREATE TABLE IF NOT EXISTS action_artifacts (
    action_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    PRIMARY KEY (action_id, artifact_id, relation_type)
);
"""

_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False, timeout=10)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.row_factory = sqlite3.Row
    return _conn


def reset_connection() -> None:
    """Close inherited DB connection after fork() — SQLite WAL is not fork-safe."""
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None


def init_db() -> None:
    config.ensure_dirs()
    _db().executescript(_SCHEMA)
    config.secure_file(config.DB_PATH)
    _migrate()


def _migrate() -> None:
    """Add columns/tables for existing databases."""
    db = _db()
    cols = {r[1] for r in db.execute("PRAGMA table_info(sessions)").fetchall()}
    for col, default in [("repo_url", None), ("tags", "'[]'"), ("visibility", "'private'"),
                          ("account_id", None), ("session_binding", None),
                          ("device_id", None), ("anchor_ts", None),
                          ("anchor_sig", None)]:
        if col not in cols:
            ddl = f"ALTER TABLE sessions ADD COLUMN {col} TEXT"
            if default:
                ddl += f" DEFAULT {default}"
            db.execute(ddl)
    # Hash chain table
    db.execute(
        "CREATE TABLE IF NOT EXISTS event_hashes "
        "(event_id TEXT PRIMARY KEY REFERENCES events(id), hash TEXT NOT NULL)"
    )
    # Deduplicate artifacts and add UNIQUE index on path (fixes cartesian join bug)
    indexes = {r[1] for r in db.execute("PRAGMA index_list(artifacts)").fetchall()}
    if "idx_artifacts_path" not in indexes:
        db.execute("DELETE FROM action_artifacts")
        db.execute("DELETE FROM artifacts WHERE rowid NOT IN (SELECT MIN(rowid) FROM artifacts GROUP BY path)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_artifacts_path ON artifacts(path)")
    # Compress legacy uncompressed metadata (TEXT → zlib BLOB)
    _migrate_compress_metadata(db)
    db.commit()


def _migrate_compress_metadata(db: sqlite3.Connection) -> None:
    """Silently compress any uncompressed TEXT metadata rows to zlib BLOBs."""
    rows = db.execute("SELECT id, metadata FROM events WHERE typeof(metadata) = 'text'").fetchall()
    if not rows:
        return
    batch, skipped = [], 0
    for r in rows:
        try:
            compressed = zlib.compress(r["metadata"].encode())
            batch.append((compressed, r["id"]))
        except Exception:
            skipped += 1
    if batch:
        db.executemany("UPDATE events SET metadata = ? WHERE id = ?", batch)
    if skipped:
        import sys
        sys.stderr.write(f"[methodproof] migration: compressed {len(batch)} events, skipped {skipped}\n")


def create_session(
    session_id: str, watch_dir: str,
    repo_url: str | None = None, tags: str = "[]", visibility: str = "private",
    account_id: str = "", session_binding: str = "", device_id: str = "",
) -> None:
    _db().execute(
        "INSERT INTO sessions (id, watch_dir, created_at, repo_url, tags, visibility, "
        "account_id, session_binding, device_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, watch_dir, time.time(), repo_url, tags, visibility,
         account_id or None, session_binding or None, device_id or None),
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


def _compress_meta(meta: dict[str, Any]) -> bytes:
    return zlib.compress(json.dumps(meta, default=str).encode())


def _decompress_meta(raw: bytes | str) -> dict[str, Any]:
    if isinstance(raw, str):
        return json.loads(raw)
    try:
        return json.loads(zlib.decompress(raw))
    except zlib.error:
        return json.loads(raw)


def insert_events(session_id: str, events: list[dict[str, Any]]) -> None:
    db = _db()
    rows = []
    for e in events:
        try:
            meta = _compress_meta(e.get("metadata", {}))
        except (TypeError, ValueError):
            meta = _compress_meta({})
        rows.append((
            e["id"], session_id, e["type"], e["timestamp"],
            e.get("duration_ms", 0), meta,
        ))
    db.executemany(
        "INSERT OR IGNORE INTO events (id, session_id, type, timestamp, duration_ms, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?)", rows,
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
    result = []
    for r in rows:
        d = dict(r)
        d["metadata"] = json.dumps(_decompress_meta(d["metadata"]))
        result.append(d)
    return result


def get_graph(session_id: str) -> dict[str, Any]:
    """Build GraphResponse-compatible dict from SQLite."""
    events = get_events(session_id)
    nodes = [{"id": e["id"], "type": "Action", "label": e["type"],
              "properties": {"timestamp": e["timestamp"], "duration_ms": e["duration_ms"],
                             "metadata": _decompress_meta(e["metadata"])}}
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

    # Resource nodes + action→resource edges
    for row in _db().execute(
        "SELECT ar.action_id, ar.resource_id, ar.relation_type, r.type AS rtype, r.identifier "
        "FROM action_resources ar JOIN resources r ON r.id = ar.resource_id "
        "WHERE ar.action_id IN (SELECT id FROM events WHERE session_id = ?)",
        (session_id,),
    ).fetchall():
        nodes.append({"id": row["resource_id"], "type": "Resource",
                       "label": row["identifier"], "properties": {"resource_type": row["rtype"]}})
        edges.append({"source": row["action_id"], "target": row["resource_id"],
                       "type": row["relation_type"], "properties": {}})

    # Artifact nodes + action→artifact edges
    for row in _db().execute(
        "SELECT aa.action_id, aa.artifact_id, aa.relation_type, a.path, a.type AS atype "
        "FROM action_artifacts aa JOIN artifacts a ON a.id = aa.artifact_id "
        "WHERE aa.action_id IN (SELECT id FROM events WHERE session_id = ?)",
        (session_id,),
    ).fetchall():
        nodes.append({"id": row["artifact_id"], "type": "Artifact",
                       "label": row["path"], "properties": {"artifact_type": row["atype"]}})
        edges.append({"source": row["action_id"], "target": row["artifact_id"],
                       "type": row["relation_type"], "properties": {}})

    # Deduplicate nodes (resources/artifacts may appear multiple times)
    seen: set[str] = set()
    unique_nodes = []
    for n in nodes:
        if n["id"] not in seen:
            seen.add(n["id"])
            unique_nodes.append(n)

    return {"nodes": unique_nodes, "edges": edges}


def update_tags(session_id: str, tags: list[str]) -> None:
    _db().execute(
        "UPDATE sessions SET tags = ? WHERE id = ?",
        (json.dumps(tags), session_id),
    )
    _db().commit()


def update_anchor(session_id: str, anchor_ts: float, anchor_sig: str) -> None:
    _db().execute(
        "UPDATE sessions SET anchor_ts = ?, anchor_sig = ? WHERE id = ?",
        (anchor_ts, anchor_sig, session_id),
    )
    _db().commit()


def update_visibility(session_id: str, visibility: str) -> None:
    _db().execute(
        "UPDATE sessions SET visibility = ? WHERE id = ?",
        (visibility, session_id),
    )
    _db().commit()


def delete_session(session_id: str) -> bool:
    """Delete a session and all its related data."""
    db = _db()
    exists = db.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not exists:
        return False
    db.execute("DELETE FROM event_hashes WHERE event_id IN (SELECT id FROM events WHERE session_id = ?)", (session_id,))
    db.execute("DELETE FROM action_artifacts WHERE action_id IN (SELECT id FROM events WHERE session_id = ?)", (session_id,))
    db.execute("DELETE FROM action_resources WHERE action_id IN (SELECT id FROM events WHERE session_id = ?)", (session_id,))
    db.execute("DELETE FROM causal_links WHERE source_id IN (SELECT id FROM events WHERE session_id = ?)", (session_id,))
    db.execute("DELETE FROM next_chain WHERE from_id IN (SELECT id FROM events WHERE session_id = ?)", (session_id,))
    db.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
    db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    db.commit()
    return True


def insert_event_hashes(hashes: list[tuple[str, str]]) -> None:
    _db().executemany(
        "INSERT OR IGNORE INTO event_hashes (event_id, hash) VALUES (?, ?)", hashes,
    )
    _db().commit()


def get_event_hashes(session_id: str) -> list[dict[str, str]]:
    rows = _db().execute(
        "SELECT eh.event_id, eh.hash FROM event_hashes eh "
        "JOIN events e ON e.id = eh.event_id "
        "WHERE e.session_id = ? ORDER BY e.timestamp",
        (session_id,),
    ).fetchall()
    return [{"event_id": r["event_id"], "hash": r["hash"]} for r in rows]


def mark_synced(session_id: str, remote_id: str) -> None:
    _db().execute(
        "UPDATE sessions SET synced = 1, remote_id = ? WHERE id = ?",
        (remote_id, session_id),
    )
    _db().commit()
