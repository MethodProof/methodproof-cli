"""Per-session model cache tests — drives the Claude Code hook's model
attribution pipeline. See `methodproof/hooks/model_cache.py`.
"""

import json
import pathlib

import pytest

from methodproof.hooks import model_cache


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Redirect cache to a tmpdir so tests don't touch a developer's real
    `~/.methodproof/hook_state/models.json`. Uses a dedicated subdir so
    the sibling-files assertion is tight."""
    cache_dir = tmp_path / "hook_state"
    cache_file = cache_dir / "models.json"
    monkeypatch.setattr(model_cache, "CACHE_PATH", cache_file)
    return cache_file


def _write_transcript(path: pathlib.Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


# ── extract_last_model ─────────────────────────────────────────────────────


def test_extract_returns_last_model_in_transcript(tmp_path: pathlib.Path) -> None:
    """When the transcript carries multiple assistant messages with
    different models, `_extract_last_model` returns the final one —
    the model that was active most recently."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        {"type": "user", "message": {"content": "hi"}},
        {"type": "assistant", "model": "claude-haiku-4-5", "message": {}},
        {"type": "user", "message": {}},
        {"type": "assistant", "model": "claude-sonnet-4-5", "message": {}},
    ])
    assert model_cache._extract_last_model(str(transcript)) == "claude-sonnet-4-5"


def test_extract_returns_none_when_no_model_field(tmp_path: pathlib.Path) -> None:
    """Transcripts without an assistant message (or without a model on
    any message) yield None — the hook falls back to 'no model attribution'."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        {"type": "user", "message": {"content": "hi"}},
    ])
    assert model_cache._extract_last_model(str(transcript)) is None


def test_extract_skips_malformed_lines(tmp_path: pathlib.Path) -> None:
    """Corrupted / partial JSON lines must not crash extraction —
    hooks run inline and cannot raise."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        'not-json\n'
        + json.dumps({"type": "assistant", "model": "claude-opus-4-7"})
        + "\n{incomplete\n"
    )
    assert model_cache._extract_last_model(str(transcript)) == "claude-opus-4-7"


def test_extract_nonexistent_file_returns_none() -> None:
    assert model_cache._extract_last_model("/nonexistent/transcript.jsonl") is None


def test_extract_uses_tail_only_on_large_transcript(tmp_path: pathlib.Path) -> None:
    """Long transcripts (>64KB) are tailed, not fully read. We seek past
    the first 64KB from the end and drop the partial first line, so a
    model set in the first KB will NOT appear. This is intentional —
    we want the CURRENT model, not the original."""
    transcript = tmp_path / "t.jsonl"
    # Pad with 80 KB of text; final assistant record at the very end.
    padding = json.dumps({"type": "user", "message": {"content": "x" * 200}}) + "\n"
    early_model = json.dumps({"type": "assistant", "model": "claude-haiku-4-5"}) + "\n"
    late_model = json.dumps({"type": "assistant", "model": "claude-opus-4-7"}) + "\n"
    transcript.write_text(early_model + padding * 400 + late_model)
    assert model_cache._extract_last_model(str(transcript)) == "claude-opus-4-7"


# ── update_from_transcript ─────────────────────────────────────────────────


def test_update_persists_and_returns_model(
    tmp_path: pathlib.Path, isolated_cache: pathlib.Path,
) -> None:
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "model": "claude-sonnet-4-5"},
    ])
    result = model_cache.update_from_transcript("sess-1", str(transcript))
    assert result == "claude-sonnet-4-5"

    data = json.loads(isolated_cache.read_text())
    assert data["sess-1"]["model"] == "claude-sonnet-4-5"
    assert isinstance(data["sess-1"]["updated_at"], (int, float))


def test_update_preserves_other_sessions(
    tmp_path: pathlib.Path, isolated_cache: pathlib.Path,
) -> None:
    """Multiple concurrent Claude Code sessions must coexist in the cache
    without clobbering each other — e.g., two worktrees each running
    `claude` simultaneously."""
    t1 = tmp_path / "t1.jsonl"
    t2 = tmp_path / "t2.jsonl"
    _write_transcript(t1, [{"type": "assistant", "model": "claude-haiku-4-5"}])
    _write_transcript(t2, [{"type": "assistant", "model": "claude-opus-4-7"}])

    model_cache.update_from_transcript("sess-A", str(t1))
    model_cache.update_from_transcript("sess-B", str(t2))

    assert model_cache.get_model("sess-A") == "claude-haiku-4-5"
    assert model_cache.get_model("sess-B") == "claude-opus-4-7"


def test_update_with_no_model_in_transcript_leaves_cache_untouched(
    tmp_path: pathlib.Path, isolated_cache: pathlib.Path,
) -> None:
    """Transcripts with no model yield None — the existing cache entry
    (from a prior update) must not be wiped. Otherwise a mid-session
    refresh against an incomplete transcript would erase attribution."""
    t1 = tmp_path / "t1.jsonl"
    _write_transcript(t1, [{"type": "assistant", "model": "claude-sonnet-4-5"}])
    model_cache.update_from_transcript("sess-X", str(t1))

    t2 = tmp_path / "t2.jsonl"
    _write_transcript(t2, [{"type": "user", "message": {"content": "hi"}}])
    result = model_cache.update_from_transcript("sess-X", str(t2))
    assert result is None
    # Cache preserved.
    assert model_cache.get_model("sess-X") == "claude-sonnet-4-5"


def test_update_with_missing_transcript_path_noops(isolated_cache: pathlib.Path) -> None:
    assert model_cache.update_from_transcript("sess-1", "") is None
    assert model_cache.update_from_transcript("", "/some/path.jsonl") is None
    assert not isolated_cache.exists()


# ── get_model / clear_session ──────────────────────────────────────────────


def test_get_model_returns_none_when_no_cache() -> None:
    assert model_cache.get_model("never-seen") is None


def test_clear_session_removes_entry(
    tmp_path: pathlib.Path, isolated_cache: pathlib.Path,
) -> None:
    t = tmp_path / "t.jsonl"
    _write_transcript(t, [{"type": "assistant", "model": "claude-sonnet-4-5"}])
    model_cache.update_from_transcript("sess-cleanup", str(t))
    assert model_cache.get_model("sess-cleanup") == "claude-sonnet-4-5"

    model_cache.clear_session("sess-cleanup")
    assert model_cache.get_model("sess-cleanup") is None


def test_corrupted_cache_file_does_not_raise(isolated_cache: pathlib.Path) -> None:
    """A user who hand-edits (or a crash that truncates) the cache file
    must not break the hook — we silently treat corrupt cache as empty."""
    isolated_cache.parent.mkdir(parents=True, exist_ok=True)
    isolated_cache.write_text("not valid JSON {{{")
    assert model_cache.get_model("anything") is None


def test_atomic_write_does_not_leave_stale_tmp_files(
    tmp_path: pathlib.Path, isolated_cache: pathlib.Path,
) -> None:
    """The save path uses NamedTemporaryFile + os.replace. After a
    successful update, the cache dir should contain only models.json —
    no leftover .tmp* files."""
    t = tmp_path / "t.jsonl"
    _write_transcript(t, [{"type": "assistant", "model": "claude-sonnet-4-5"}])
    model_cache.update_from_transcript("sess-1", str(t))
    siblings = list(isolated_cache.parent.iterdir())
    assert siblings == [isolated_cache], f"stale tmp files: {siblings}"


# ── Hook integration: model flows into emitted event metadata ─────────────

def test_claude_code_hook_pretooluse_attaches_cached_model(
    tmp_path: pathlib.Path, isolated_cache: pathlib.Path,
) -> None:
    """End-to-end: a PreToolUse payload emitted by the Python hook
    carries the session's currently-cached model. This is the whole
    point of the cache — tool events need model attribution without
    re-reading the transcript on every fire."""
    from methodproof.hooks import claude_code as hook

    # Prime the cache with this session's model.
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "model": "claude-sonnet-4-5"},
    ])
    model_cache.update_from_transcript("sess-test", str(transcript))

    # Simulate the PreToolUse stdin payload Claude Code would send.
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-test",
        "tool_name": "Edit",
        "tool_use_id": "toolu_test",
        "tool_input": {"file_path": "/abs/path/app.py",
                       "old_string": "x", "new_string": "y"},
    }
    meta = hook._META_EXTRACTORS["PreToolUse"](payload)
    assert meta["model"] == "claude-sonnet-4-5"
    assert meta["tool_name"] == "Edit"
    assert meta["tool_input"]["file_path"] == "/abs/path/app.py"


def test_claude_code_hook_omits_model_when_cache_empty(tmp_path: pathlib.Path) -> None:
    """No cache entry → no ``model`` key in metadata (not a ``None``
    placeholder). Downstream consumers use `metadata.get("model")` and
    a missing key is the honest answer when we don't know."""
    from methodproof.hooks import claude_code as hook

    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "never-cached",
        "tool_name": "Edit",
        "tool_use_id": "toolu_2",
        "tool_input": {"file_path": "/abs/foo.py"},
    }
    meta = hook._META_EXTRACTORS["PreToolUse"](payload)
    assert "model" not in meta
