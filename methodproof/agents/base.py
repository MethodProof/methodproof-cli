"""Shared telemetry primitives — one log, one emit, one flush."""

import json
import sys
import threading
import time
import uuid
from typing import Any

from methodproof import store

_session_id = ""
_initialized = False
_e2e_key: bytes | None = None
_capture: dict[str, bool] = {}
_live_mode = False
_lock = threading.Lock()
_buffer: list[dict[str, Any]] = []
_FLUSH_SIZE = 50
_MAX_RETRIES = 3
_prev_hash = "genesis"

# Maps event types to the capture category that gates them
_EVENT_GATES: dict[str, str] = {
    "terminal_cmd": "terminal_commands",
    "test_run": "test_results",
    "file_create": "file_changes",
    "file_edit": "file_changes",
    "file_delete": "file_changes",
    "git_commit": "git_commits",
    "llm_prompt": "ai_prompts",
    "agent_prompt": "ai_prompts",
    "llm_completion": "ai_responses",
    "agent_completion": "ai_responses",
    "agent_tool_dispatch": "ai_responses",
    "agent_tool_result": "ai_responses",
    "agent_skill_invoke": "ai_responses",
    "agent_session_event": "ai_responses",
    "inline_completion_shown": "ai_responses",
    "inline_completion_accepted": "ai_responses",
    "inline_completion_rejected": "ai_responses",
    "browser_visit": "browser",
    "browser_search": "browser",
    "browser_tab_switch": "browser",
    "browser_copy": "browser",
    "browser_ai_chat": "browser",
    "music_playing": "music",
    "environment_profile": "environment_analysis",
}

# Maps capture categories to (event_type, field) pairs for field-level gating.
# When the category is disabled, these fields are stripped from emitted events.
# When enabled (code_capture), these fields are populated by the agent.
_FIELD_GATES: dict[str, list[tuple[str, str]]] = {
    "command_output": [("terminal_cmd", "output_snippet")],
    "code_capture": [("file_edit", "diff"), ("git_commit", "diff")],
}


def init(session_id: str, live: bool = False) -> None:
    global _session_id, _initialized, _e2e_key, _capture, _live_mode, _prev_hash
    _session_id = session_id
    _initialized = True
    _live_mode = live
    _prev_hash = "genesis"
    from methodproof import config
    cfg = config.load()
    raw = cfg.get("e2e_key", "")
    _e2e_key = bytes.fromhex(raw) if raw else None
    _capture = cfg.get("capture", {})


def log(level: str, event: str, **kw: object) -> None:
    entry = {"ts": time.time(), "level": level, "event": event, "sid": _session_id, **kw}
    sys.stderr.write(json.dumps(entry, default=str) + "\n")


def emit(event_type: str, metadata: dict[str, Any]) -> None:
    if not _initialized:
        log("warning", "emit.before_init", type=event_type)
        return
    # Event-level consent gate
    gate = _EVENT_GATES.get(event_type)
    if gate and not _capture.get(gate, True):
        return
    # Field-level consent gate — strip opted-out fields
    for category, pairs in _FIELD_GATES.items():
        for etype, field in pairs:
            if event_type == etype and not _capture.get(category, True):
                metadata.pop(field, None)

    entry = {
        "id": uuid.uuid4().hex,
        "session_id": _session_id,
        "type": event_type,
        "timestamp": time.time(),
        "duration_ms": metadata.pop("duration_ms", 0),
        "metadata": metadata,
    }
    if _e2e_key:
        from methodproof.crypto import encrypt_metadata
        entry["metadata"] = encrypt_metadata(dict(entry["metadata"]), _e2e_key)
    global _prev_hash
    from methodproof.integrity import compute_event_hash
    entry["_chain_hash"] = compute_event_hash(entry, _prev_hash)
    _prev_hash = entry["_chain_hash"]
    if _live_mode:
        from methodproof import live as live_mod
        live_mod.send(entry)
    with _lock:
        _buffer.append(entry)
        if len(_buffer) >= _FLUSH_SIZE:
            _flush_locked()


def flush() -> None:
    with _lock:
        _flush_locked()


def _flush_locked() -> None:
    if not _buffer:
        return
    batch = list(_buffer)
    hashes = [(e["id"], e.pop("_chain_hash")) for e in batch if "_chain_hash" in e]
    for attempt in range(_MAX_RETRIES):
        try:
            store.insert_events(_session_id, batch)
            if hashes:
                store.insert_event_hashes(hashes)
            _buffer.clear()
            return
        except Exception as exc:
            log("warning", "flush.retry", attempt=attempt + 1, error=str(exc))
            time.sleep(0.1 * (attempt + 1))
    # Final attempt failed — keep events in buffer for next flush cycle
    log("error", "flush.failed", count=len(batch), retries=_MAX_RETRIES)
