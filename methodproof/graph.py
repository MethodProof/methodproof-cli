"""Graph builder — NEXT chain + causal links from SQLite events."""

import json
import uuid
from typing import Any

from methodproof.store import _db


def build(session_id: str) -> dict[str, int]:
    """Build temporal chain, causal links, and resource/artifact edges."""
    db = _db()
    stats = {"next": 0, "causal": 0, "resources": 0, "artifacts": 0}

    events = db.execute(
        "SELECT id, type, timestamp, metadata FROM events "
        "WHERE session_id = ? ORDER BY timestamp",
        (session_id,),
    ).fetchall()
    if not events:
        return stats

    # NEXT chain
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
    stats["causal"] += _link_pasted(db, session_id)

    # Resources
    for e in events:
        meta = json.loads(e["metadata"])
        if e["type"] in ("llm_prompt", "llm_completion") and "model" in meta:
            _ensure_resource(db, "llm_model", meta["model"])
            stats["resources"] += 1

    # Artifacts
    for e in events:
        meta = json.loads(e["metadata"])
        if e["type"] in ("file_create", "file_edit") and "path" in meta:
            _ensure_artifact(db, meta["path"], meta.get("size", 0))
            stats["artifacts"] += 1

    # Action → Resource links (SENT_TO, CONSUMED)
    _link_action_resources(db, session_id)

    # Action → Artifact links (PRODUCED, MODIFIED)
    _link_action_artifacts(db, session_id)

    db.commit()
    return stats


def _link(
    db: object, sid: str, src_type: str, tgt_type: str,
    rel: str, window_sec: int, match_model: bool = False,
) -> int:
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
    return db.execute(sql, (rel, sid, src_type, tgt_type, window_sec)).rowcount


def _link_pasted(db: object, sid: str) -> int:
    """browser_copy → file_edit: ≤30s, content length within 20%."""
    sql = """
    INSERT OR IGNORE INTO causal_links (source_id, target_id, type, confidence)
    SELECT s.id, t.id, 'PASTED_FROM', 0.7
    FROM events s JOIN events t ON t.session_id = s.session_id
    WHERE s.session_id = ? AND s.type = 'browser_copy' AND t.type = 'file_edit'
      AND t.timestamp > s.timestamp AND (t.timestamp - s.timestamp) <= 30
      AND abs(json_extract(t.metadata, '$.lines_added') * 40.0
            - json_extract(s.metadata, '$.text_length'))
          < json_extract(s.metadata, '$.text_length') * 0.2
    """
    return db.execute(sql, (sid,)).rowcount


def _link_action_resources(db: object, sid: str) -> None:
    """Link llm_prompt → SENT_TO → Resource, llm_completion → CONSUMED → Resource."""
    db.execute("""
    INSERT OR IGNORE INTO action_resources (action_id, resource_id, relation_type, metadata)
    SELECT e.id, r.id, 'SENT_TO', '{}'
    FROM events e JOIN resources r ON r.identifier = json_extract(e.metadata, '$.model')
    WHERE e.session_id = ? AND e.type = 'llm_prompt' AND r.type = 'llm_model'
    """, (sid,))
    db.execute("""
    INSERT OR IGNORE INTO action_resources (action_id, resource_id, relation_type, metadata)
    SELECT e.id, r.id, 'CONSUMED', '{}'
    FROM events e JOIN resources r ON r.identifier = json_extract(e.metadata, '$.model')
    WHERE e.session_id = ? AND e.type = 'llm_completion' AND r.type = 'llm_model'
    """, (sid,))


def _link_action_artifacts(db: object, sid: str) -> None:
    """Link file_create → PRODUCED → Artifact, file_edit → MODIFIED → Artifact."""
    db.execute("""
    INSERT OR IGNORE INTO action_artifacts (action_id, artifact_id, relation_type)
    SELECT e.id, a.id, 'PRODUCED'
    FROM events e JOIN artifacts a ON a.path = json_extract(e.metadata, '$.path')
    WHERE e.session_id = ? AND e.type = 'file_create'
    """, (sid,))
    db.execute("""
    INSERT OR IGNORE INTO action_artifacts (action_id, artifact_id, relation_type)
    SELECT e.id, a.id, 'MODIFIED'
    FROM events e JOIN artifacts a ON a.path = json_extract(e.metadata, '$.path')
    WHERE e.session_id = ? AND e.type = 'file_edit'
    """, (sid,))


def _ensure_resource(db: object, rtype: str, identifier: str) -> None:
    db.execute(
        "INSERT OR IGNORE INTO resources (id, type, identifier) VALUES (?, ?, ?)",
        (uuid.uuid4().hex, rtype, identifier))


def _ensure_artifact(db: object, path: str, size: int) -> None:
    db.execute(
        "INSERT OR IGNORE INTO artifacts (id, path, size_bytes) VALUES (?, ?, ?)",
        (uuid.uuid4().hex, path, size))
