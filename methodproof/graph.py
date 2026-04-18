"""Graph builder — NEXT chain + causal links from SQLite events."""

import json
import time
import uuid
from typing import Any

from methodproof.store import _compress_meta, _db, _decompress_meta


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
    stats["causal"] += _link_nearest(db, session_id, "llm_prompt",
                                      "llm_completion", "RECEIVED", "model")
    stats["causal"] += _link_until_next(db, session_id, "llm_completion",
                                         "file_edit", "INFORMED")
    stats["causal"] += _link_until_next(db, session_id, "web_search",
                                         "web_visit", "LED_TO")
    stats["causal"] += _link_until_next(db, session_id, "browser_search",
                                         "browser_visit", "LED_TO")
    stats["causal"] += _link_pasted(db, session_id)
    stats["causal"] += _link_nearest(db, session_id, "agent_prompt",
                                      "agent_completion", "RECEIVED", "model")
    stats["causal"] += _link_until_next(db, session_id, "agent_completion",
                                         "file_edit", "INFORMED")

    # Resources
    for e in events:
        meta = _decompress_meta(e["metadata"])
        if e["type"] in ("llm_prompt", "llm_completion") and "model" in meta:
            _ensure_resource(db, "llm_model", meta["model"])
            stats["resources"] += 1
        elif e["type"] in ("agent_prompt", "agent_completion") and "gateway" in meta:
            _ensure_resource(db, "agent_gateway", meta["gateway"])
            stats["resources"] += 1

    # Artifacts
    for e in events:
        meta = _decompress_meta(e["metadata"])
        if e["type"] in ("file_create", "file_edit") and "path" in meta:
            _ensure_artifact(db, meta["path"], meta.get("size", 0))
            stats["artifacts"] += 1

    # Action → Resource links (SENT_TO, CONSUMED)
    _link_action_resources(db, session_id)

    # Action → Artifact links (PRODUCED, MODIFIED)
    _link_action_artifacts(db, session_id)

    # Prompt outcome metrics
    try:
        from methodproof.analysis import compute_outcomes
        outcomes = compute_outcomes(session_id)
        if outcomes and outcomes.get("total_prompts", 0) > 0:
            db.execute(
                "INSERT OR IGNORE INTO events "
                "(id, session_id, type, timestamp, duration_ms, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, session_id, "prompt_outcomes",
                 time.time(), 0, _compress_meta(outcomes)),
            )
            stats["outcomes"] = 1
    except Exception as exc:
        from methodproof.agents.base import log
        log("warning", "graph.outcomes_failed", session_id=session_id, error=str(exc))

    db.commit()
    return stats


def _link_nearest(
    db: object, sid: str, src_type: str, tgt_type: str,
    rel: str, match_field: str | None = None,
) -> int:
    """1:1 nearest-neighbor pairing. No time window."""
    rows = db.execute(
        "SELECT id, type, timestamp, metadata FROM events "
        "WHERE session_id = ? AND type IN (?, ?) ORDER BY timestamp",
        (sid, src_type, tgt_type),
    ).fetchall()
    claimed: set[str] = set()
    pairs: list[tuple[str, str, str]] = []
    for src in rows:
        if src["type"] != src_type:
            continue
        src_val = _decompress_meta(src["metadata"]).get(match_field) if match_field else None
        for tgt in rows:
            if tgt["type"] != tgt_type or tgt["id"] in claimed or tgt["timestamp"] <= src["timestamp"]:
                continue
            if match_field and _decompress_meta(tgt["metadata"]).get(match_field) != src_val:
                continue
            pairs.append((src["id"], tgt["id"], rel))
            claimed.add(tgt["id"])
            break
    if pairs:
        db.executemany(
            "INSERT OR IGNORE INTO causal_links (source_id, target_id, type) "
            "VALUES (?, ?, ?)", pairs)
    return len(pairs)


def _link_until_next(
    db: object, sid: str, src_type: str, tgt_type: str, rel: str,
) -> int:
    """Link source to all targets until the next source event."""
    rows = db.execute(
        "SELECT id, type FROM events "
        "WHERE session_id = ? AND type IN (?, ?) ORDER BY timestamp",
        (sid, src_type, tgt_type),
    ).fetchall()
    pairs: list[tuple[str, str, str]] = []
    current_src: str | None = None
    for ev in rows:
        if ev["type"] == src_type:
            current_src = ev["id"]
        elif current_src:
            pairs.append((current_src, ev["id"], rel))
    if pairs:
        db.executemany(
            "INSERT OR IGNORE INTO causal_links (source_id, target_id, type) "
            "VALUES (?, ?, ?)", pairs)
    return len(pairs)


def _link_pasted(db: object, sid: str) -> int:
    """browser_copy → nearest file_edit with content length within 20%."""
    rows = db.execute(
        "SELECT id, type, timestamp, metadata FROM events "
        "WHERE session_id = ? AND type IN ('browser_copy', 'file_edit') "
        "ORDER BY timestamp", (sid,),
    ).fetchall()
    claimed: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for src in rows:
        if src["type"] != "browser_copy":
            continue
        src_len = _decompress_meta(src["metadata"]).get("text_length", 0)
        if not src_len:
            continue
        for tgt in rows:
            if tgt["type"] != "file_edit" or tgt["id"] in claimed or tgt["timestamp"] <= src["timestamp"]:
                continue
            if abs(_decompress_meta(tgt["metadata"]).get("lines_added", 0) * 40 - src_len) < src_len * 0.2:
                pairs.append((src["id"], tgt["id"]))
                claimed.add(tgt["id"])
                break
    if pairs:
        db.executemany(
            "INSERT OR IGNORE INTO causal_links (source_id, target_id, type, confidence) "
            "VALUES (?, ?, 'PASTED_FROM', 0.7)", pairs)
    return len(pairs)


def _link_action_resources(db: object, sid: str) -> None:
    """Link prompt → SENT_TO → Resource, completion → CONSUMED → Resource."""
    db.execute("""
    INSERT OR IGNORE INTO action_resources (action_id, resource_id, relation_type, metadata)
    SELECT e.id, r.id, 'SENT_TO', '{}'
    FROM events e JOIN resources r ON r.identifier = json_extract(mp_json(e.metadata), '$.model')
    WHERE e.session_id = ? AND e.type = 'llm_prompt' AND r.type = 'llm_model'
    """, (sid,))
    db.execute("""
    INSERT OR IGNORE INTO action_resources (action_id, resource_id, relation_type, metadata)
    SELECT e.id, r.id, 'CONSUMED', '{}'
    FROM events e JOIN resources r ON r.identifier = json_extract(mp_json(e.metadata), '$.model')
    WHERE e.session_id = ? AND e.type = 'llm_completion' AND r.type = 'llm_model'
    """, (sid,))
    # Agent gateway links
    db.execute("""
    INSERT OR IGNORE INTO action_resources (action_id, resource_id, relation_type, metadata)
    SELECT e.id, r.id, 'SENT_TO', '{}'
    FROM events e JOIN resources r ON r.identifier = json_extract(mp_json(e.metadata), '$.gateway')
    WHERE e.session_id = ? AND e.type = 'agent_prompt' AND r.type = 'agent_gateway'
    """, (sid,))


def _link_action_artifacts(db: object, sid: str) -> None:
    """Link file_create → PRODUCED → Artifact, file_edit → MODIFIED → Artifact."""
    db.execute("""
    INSERT OR IGNORE INTO action_artifacts (action_id, artifact_id, relation_type)
    SELECT e.id, a.id, 'PRODUCED'
    FROM events e JOIN artifacts a ON a.path = json_extract(mp_json(e.metadata), '$.path')
    WHERE e.session_id = ? AND e.type = 'file_create'
    """, (sid,))
    db.execute("""
    INSERT OR IGNORE INTO action_artifacts (action_id, artifact_id, relation_type)
    SELECT e.id, a.id, 'MODIFIED'
    FROM events e JOIN artifacts a ON a.path = json_extract(mp_json(e.metadata), '$.path')
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
