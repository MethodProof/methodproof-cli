"""Graph builder — NEXT chain + causal links from SQLite events."""

import json
import uuid
from typing import Any

from methodproof.store import _db


def build(session_id: str) -> dict[str, int]:
    """Build temporal chain and causal links. Returns stats."""
    db = _db()

    stats = {"next": 0, "causal": 0, "resources": 0, "artifacts": 0}

    events = db.execute(
        "SELECT id, type, timestamp, metadata FROM events "
        "WHERE session_id = ? ORDER BY timestamp",
        (session_id,),
    ).fetchall()
    if not events:
        return stats

    # NEXT chain (needs 2+ events)
    db.execute(
        "DELETE FROM next_chain WHERE from_id IN "
        "(SELECT id FROM events WHERE session_id = ?)", (session_id,))
    if len(events) >= 2:
        pairs = [(events[i]["id"], events[i + 1]["id"],
                  (events[i + 1]["timestamp"] - events[i]["timestamp"]) * 1000)
                 for i in range(len(events) - 1)]
        db.executemany("INSERT OR IGNORE INTO next_chain VALUES (?, ?, ?)", pairs)
        stats["next"] = len(pairs)

    # Causal links
    db.execute(
        "DELETE FROM causal_links WHERE source_id IN "
        "(SELECT id FROM events WHERE session_id = ?)", (session_id,))
    stats["causal"] += _link(db, session_id, "llm_prompt", "llm_completion",
                              "RECEIVED", 60, match_model=True)
    stats["causal"] += _link(db, session_id, "llm_completion", "file_edit",
                              "INFORMED", 60)
    stats["causal"] += _link(db, session_id, "web_search", "web_visit",
                              "LED_TO", 120)
    stats["causal"] += _link(db, session_id, "browser_search", "browser_visit",
                              "LED_TO", 120)

    # Resources
    for e in events:
        meta = json.loads(e["metadata"])
        if e["type"] in ("llm_prompt", "llm_completion") and "model" in meta:
            rid = _ensure_resource(db, "llm_model", meta["model"])
            stats["resources"] += 1 if rid else 0

    # Artifacts
    for e in events:
        meta = json.loads(e["metadata"])
        if e["type"] in ("file_create", "file_edit") and "path" in meta:
            _ensure_artifact(db, meta["path"], meta.get("size", 0))
            stats["artifacts"] += 1

    db.commit()
    return stats


def _link(
    db: object, sid: str,
    src_type: str, tgt_type: str, rel: str,
    window_sec: int, match_model: bool = False,
) -> int:
    """Insert causal links between event types within a time window."""
    model_clause = (
        "AND json_extract(s.metadata, '$.model') = json_extract(t.metadata, '$.model')"
        if match_model else ""
    )
    sql = f"""
    INSERT OR IGNORE INTO causal_links (source_id, target_id, type)
    SELECT s.id, t.id, ?
    FROM events s JOIN events t ON t.session_id = s.session_id
    WHERE s.session_id = ? AND s.type = ? AND t.type = ?
      AND t.timestamp > s.timestamp
      AND (t.timestamp - s.timestamp) <= ?
      {model_clause}
    """
    cur = db.execute(sql, (rel, sid, src_type, tgt_type, window_sec))
    return cur.rowcount


def _ensure_resource(db: object, rtype: str, identifier: str) -> bool:
    try:
        db.execute(
            "INSERT OR IGNORE INTO resources (id, type, identifier) VALUES (?, ?, ?)",
            (uuid.uuid4().hex, rtype, identifier))
        return True
    except Exception:
        return False


def _ensure_artifact(db: object, path: str, size: int) -> None:
    db.execute(
        "INSERT OR IGNORE INTO artifacts (id, path, size_bytes) VALUES (?, ?, ?)",
        (uuid.uuid4().hex, path, size))
