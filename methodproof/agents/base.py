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
_account_id = ""
_journal_mode = False
_verbose = False
_streaming = False

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
    "prompt_outcomes": "ai_prompts",
    "ai_cli_start": "ai_prompts",
    "ai_cli_end": "ai_responses",
    # Hook lifecycle events (all AI tools)
    "user_prompt": "ai_prompts",
    "tool_call": "ai_responses",
    "tool_result": "ai_responses",
    "task_start": "ai_responses",
    "task_end": "ai_responses",
    "agent_launch": "ai_responses",
    "agent_complete": "ai_responses",
    "claude_session_start": "ai_prompts",
    "codex_session_start": "ai_prompts",
    "codex_session_end": "ai_responses",
    "gemini_session_start": "ai_prompts",
    "gemini_session_end": "ai_responses",
    "kiro_session_start": "ai_prompts",
    "kiro_session_end": "ai_responses",
}

# Maps capture categories to (event_type, field) pairs for field-level gating.
# When the category is disabled, these fields are stripped from emitted events.
# When enabled (code_capture), these fields are populated by the agent.
_FIELD_GATES: dict[str, list[tuple[str, str]]] = {
    "command_output": [("terminal_cmd", "output_snippet")],
    "code_capture": [("file_edit", "diff"), ("git_commit", "diff")],
}


def _load_encryption_key(cfg: dict) -> bytes | None:
    """Load encryption key: individual E2E > db_key from keychain > legacy e2e_key."""
    account_id = cfg.get("account_id", "")
    # Individual E2E key — highest priority when session is E2E
    if account_id and cfg.get("e2e_fingerprint") and cfg.get("_session_e2e"):
        from methodproof.keychain import load_secret
        e2e_key = load_secret(f"e2e:{account_id}")
        if e2e_key:
            return e2e_key
    # Local db_key (for SQLite encryption)
    if account_id and cfg.get("master_key_fingerprint"):
        from methodproof.keychain import load_secret
        from methodproof.kdf import derive_master, derive_db_key
        master_entropy = load_secret(account_id)
        if master_entropy:
            master = derive_master(master_entropy)
            return derive_db_key(master, account_id)
    raw = cfg.get("e2e_key", "")
    return bytes.fromhex(raw) if raw else None


def init(session_id: str, live: bool = False, verbose: bool = False, streaming: bool = False) -> None:
    global _session_id, _initialized, _e2e_key, _capture, _live_mode, _prev_hash, _journal_mode, _account_id, _verbose, _streaming
    _session_id = session_id
    _initialized = True
    _live_mode = live
    _verbose = verbose
    _streaming = streaming
    _prev_hash = "genesis"
    from methodproof import config
    cfg = config.load()
    _e2e_key = _load_encryption_key(cfg)
    _capture = cfg.get("capture", {})
    _journal_mode = cfg.get("journal_mode", False)
    _account_id = cfg.get("account_id", "")
    if _verbose or _streaming:
        active = [k for k, v in _capture.items() if v]
        log("info", "base.init", encryption=bool(_e2e_key), journal=_journal_mode,
            live=_live_mode, capture=active)


def log(level: str, event: str, **kw: object) -> None:
    entry = {"ts": time.time(), "level": level, "event": event, "sid": _session_id, **kw}
    sys.stderr.write(json.dumps(entry, default=str) + "\n")


def is_content_captured() -> bool:
    """True when code_capture consent is on (journal/Pro mode). Agents use this
    to decide whether to include line-level diff content alongside structural
    metadata."""
    return bool(_capture.get("code_capture", False))


def emit(event_type: str, metadata: dict[str, Any]) -> None:
    if not _initialized:
        log("warning", "emit.before_init", type=event_type)
        return
    # Event-level consent gate
    gate = _EVENT_GATES.get(event_type)
    if gate and not _capture.get(gate, True):
        log("debug", "emit.consent_blocked", type=event_type, gate=gate)
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
    with _lock:
        global _prev_hash
        from methodproof.integrity import compute_event_hash
        entry["_chain_hash"] = compute_event_hash(entry, _prev_hash, _account_id)
        _prev_hash = entry["_chain_hash"]
        _buffer.append(entry)
        if len(_buffer) >= _FLUSH_SIZE:
            _flush_locked()
    if _verbose:
        log("debug", "emit.buffered", type=event_type, buffer=len(_buffer))
    if _streaming:
        _stream_event(entry)
    if _live_mode:
        from methodproof import live as live_mod
        live_mod.send(entry)


def flush() -> None:
    with _lock:
        _flush_locked()


def _flush_locked() -> None:
    if not _buffer:
        return
    batch = list(_buffer)
    hashes = [(e["id"], e.pop("_chain_hash")) for e in batch if "_chain_hash" in e]
    if _verbose or _streaming:
        types = [e["type"] for e in batch]
        log("info", "flush.start", count=len(batch), types=types)
    for attempt in range(_MAX_RETRIES):
        try:
            store.insert_events(_session_id, batch)
            if hashes:
                store.insert_event_hashes(hashes)
            if _verbose or _streaming:
                log("info", "flush.ok", count=len(batch))
            _buffer.clear()
            return
        except Exception as exc:
            log("warning", "flush.retry", attempt=attempt + 1, error=str(exc))
            time.sleep(0.1 * (attempt + 1))
    log("error", "flush.failed", count=len(batch), retries=_MAX_RETRIES)


def _stream_event(entry: dict[str, Any]) -> None:
    """Print a human-readable event line to stdout for --streaming mode."""
    ts = time.strftime("%H:%M:%S", time.localtime(entry["timestamp"]))
    etype = entry["type"]
    meta = entry.get("metadata", {})
    # Build a compact summary per event type
    detail = ""
    if etype == "file_edit":
        detail = f'{meta.get("path", "?")} +{meta.get("lines_added", 0)}-{meta.get("lines_removed", 0)}'
    elif etype == "file_create":
        detail = f'{meta.get("path", "?")} ({meta.get("size", 0)}B)'
    elif etype == "file_delete":
        detail = meta.get("path", "?")
    elif etype == "terminal_cmd":
        detail = f'{meta.get("command", "?")[:60]} → exit {meta.get("exit_code", "?")}'
    elif etype == "test_run":
        detail = f'{meta.get("framework", "?")} {meta.get("passed", 0)}✓ {meta.get("failed", 0)}✗'
    elif etype == "git_commit":
        detail = f'{meta.get("hash", "?")} {meta.get("message", "")[:50]}'
    elif etype in ("llm_prompt", "agent_prompt", "user_prompt"):
        detail = f'len={meta.get("prompt_length", meta.get("message_length", "?"))}'
    elif etype in ("llm_completion", "agent_completion"):
        detail = f'len={meta.get("response_length", "?")}'
    elif etype == "music_playing":
        detail = f'{meta.get("artist", "?")} — {meta.get("track", "?")}'
    elif etype.startswith("browser_"):
        detail = meta.get("url", meta.get("query", ""))[:60]
    elif etype == "environment_profile":
        detail = f'{meta.get("tool_count", "?")} tools'
    else:
        keys = list(meta.keys())[:4]
        detail = ", ".join(f"{k}={meta[k]}" for k in keys) if keys else ""
    sys.stdout.write(f"  [{ts}] {etype:30s} {detail}\n")
    sys.stdout.flush()
