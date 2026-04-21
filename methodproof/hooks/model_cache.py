"""Per-session model cache for Claude Code capture.

Claude Code doesn't pass the active model in every hook payload — only the
transcript JSONL carries it. Re-reading the transcript on every PreToolUse
would add tens of ms to each hook invocation. This module keeps a tiny
JSON cache at ``~/.methodproof/hook_state/models.json`` mapping Claude
session_id → (model, updated_at), refreshed once per turn at the cheap
waypoints (``SessionStart``, ``UserPromptSubmit``, ``Stop``) and read
cheaply on every tool event.

Atomic writes via ``tempfile.NamedTemporaryFile`` + ``os.replace`` so
concurrent hook invocations never corrupt the file.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import time


CACHE_PATH = pathlib.Path.home() / ".methodproof" / "hook_state" / "models.json"
# How far back to scan a transcript for the last assistant message's model.
# Transcripts are JSONL append-only, so tail is all we need. 200 lines covers
# a typical turn plus headroom; we're not trying to reconstruct history.
_TAIL_BYTES = 64 * 1024


def _load() -> dict:
    try:
        with CACHE_PATH.open("r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write — write to a tmp file in the same dir, rename over.
    with tempfile.NamedTemporaryFile(
        mode="w", dir=str(CACHE_PATH.parent), delete=False, suffix=".json",
    ) as tmp:
        json.dump(data, tmp)
        tmp_path = tmp.name
    os.replace(tmp_path, CACHE_PATH)


def _extract_last_model(transcript_path: str) -> str | None:
    """Read the tail of a transcript JSONL and return the most recent
    ``model`` field from an assistant message. ``None`` if the transcript
    is missing, unreadable, or contains no model annotation.
    """
    path = pathlib.Path(transcript_path)
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > _TAIL_BYTES:
                f.seek(size - _TAIL_BYTES)
                # Drop partial first line after a seek
                f.readline()
            blob = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    last_model: str | None = None
    for line in blob.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        # Claude Code transcript shape: top-level "model" on assistant messages.
        model = rec.get("model")
        if isinstance(model, str) and model:
            last_model = model
    return last_model


def update_from_transcript(session_id: str, transcript_path: str) -> str | None:
    """Read the transcript tail, extract the most recent model, and persist
    it in the cache keyed by ``session_id``. Returns the model string (or
    ``None`` if extraction failed — cache untouched in that case).
    """
    if not session_id or not transcript_path:
        return None
    model = _extract_last_model(transcript_path)
    if model is None:
        return None
    try:
        data = _load()
        data[session_id] = {"model": model, "updated_at": time.time()}
        _save(data)
    except OSError:
        # Cache is best-effort. A write failure must not break the hook.
        return model
    return model


def get_model(session_id: str) -> str | None:
    """Return the cached model for ``session_id``, or ``None`` if no cache
    entry exists. Never raises — the cache is best-effort."""
    if not session_id:
        return None
    try:
        data = _load()
    except OSError:
        return None
    entry = data.get(session_id)
    if not isinstance(entry, dict):
        return None
    model = entry.get("model")
    return model if isinstance(model, str) and model else None


def clear_session(session_id: str) -> None:
    """Remove a session's cache entry. Called on ``SessionEnd`` so cache
    size stays bounded over time."""
    if not session_id:
        return
    try:
        data = _load()
        if session_id in data:
            del data[session_id]
            _save(data)
    except OSError:
        return


# CLI entry so the shell hook can do `python3 -m methodproof.hooks.model_cache ...`
# on rare events (SessionStart / Stop / SessionEnd). The hot read path in shell
# uses jq directly on the cache file — no Python subprocess needed.
def _main() -> int:
    import sys
    args = sys.argv[1:]
    if len(args) < 1:
        return 1
    cmd = args[0]
    if cmd == "update" and len(args) == 3:
        model = update_from_transcript(args[1], args[2])
        if model:
            print(model)
        return 0
    if cmd == "get" and len(args) == 2:
        model = get_model(args[1])
        if model:
            print(model)
        return 0
    if cmd == "clear" and len(args) == 2:
        clear_session(args[1])
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
