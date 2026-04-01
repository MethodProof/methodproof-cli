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
_lock = threading.Lock()
_buffer: list[dict[str, Any]] = []
_FLUSH_SIZE = 50
_MAX_RETRIES = 3


def init(session_id: str) -> None:
    global _session_id, _initialized
    _session_id = session_id
    _initialized = True


def log(level: str, event: str, **kw: object) -> None:
    entry = {"ts": time.time(), "level": level, "event": event, "sid": _session_id, **kw}
    sys.stderr.write(json.dumps(entry, default=str) + "\n")


def emit(event_type: str, metadata: dict[str, Any]) -> None:
    if not _initialized:
        log("warning", "emit.before_init", type=event_type)
        return
    entry = {
        "id": uuid.uuid4().hex,
        "session_id": _session_id,
        "type": event_type,
        "timestamp": time.time(),
        "duration_ms": metadata.pop("duration_ms", 0),
        "metadata": metadata,
    }
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
    for attempt in range(_MAX_RETRIES):
        try:
            store.insert_events(_session_id, batch)
            _buffer.clear()
            return
        except Exception as exc:
            log("warning", "flush.retry", attempt=attempt + 1, error=str(exc))
            time.sleep(0.1 * (attempt + 1))
    # Final attempt failed — keep events in buffer for next flush cycle
    log("error", "flush.failed", count=len(batch), retries=_MAX_RETRIES)
