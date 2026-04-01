"""Shared telemetry primitives — one log, one emit, one flush."""

import json
import sys
import threading
import time
import uuid
from typing import Any

from methodproof import store

_session_id = ""
_lock = threading.Lock()
_buffer: list[dict[str, Any]] = []
_FLUSH_SIZE = 50


def init(session_id: str) -> None:
    global _session_id
    _session_id = session_id


def log(level: str, event: str, **kw: object) -> None:
    entry = {"ts": time.time(), "level": level, "event": event, "sid": _session_id, **kw}
    sys.stderr.write(json.dumps(entry, default=str) + "\n")


def emit(event_type: str, metadata: dict[str, Any]) -> None:
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
    try:
        store.insert_events(_session_id, list(_buffer))
    except Exception as exc:
        log("error", "flush.failed", error=str(exc))
    _buffer.clear()
