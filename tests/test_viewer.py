"""Tests for viewer.py — local session viewer."""

import json
import time
import uuid

import pytest

from methodproof import config, store
from methodproof.viewer import _duration, _event_summary, _offset, _truncate, view


# ── _truncate ──


def test_truncate_short():
    assert _truncate("hello", 10) == "hello"


def test_truncate_exact():
    assert _truncate("12345", 5) == "12345"


def test_truncate_long():
    assert _truncate("hello world", 5) == "hello…"


# ── _offset ──


def test_offset_zero():
    assert _offset(100.0, 100.0) == "0:00"


def test_offset_positive():
    assert _offset(165.0, 100.0) == "1:05"


def test_offset_negative_clamps():
    assert _offset(90.0, 100.0) == "0:00"


# ── _duration ──


def test_duration_active():
    assert _duration({"created_at": 100.0}) == "active"


def test_duration_completed():
    assert _duration({"created_at": 100.0, "completed_at": 225.0}) == "2:05"


# ── _event_summary ──


def test_event_summary_file_edit():
    result = _event_summary("file_edit", {"path": "app.py", "language": "python", "line_count": 42})
    assert "app.py" in result
    assert "python" in result
    assert "42 lines" in result


def test_event_summary_git_commit():
    result = _event_summary("git_commit", {"message": "fix bug", "files_changed": 3})
    assert "fix bug" in result
    assert "3 files" in result


def test_event_summary_llm_prompt():
    result = _event_summary("llm_prompt", {"model": "claude-3", "token_count": 500})
    assert "claude-3" in result
    assert "500 tokens" in result


def test_event_summary_terminal_cmd():
    result = _event_summary("terminal_cmd", {"command": "pytest tests/"})
    assert "pytest" in result


def test_event_summary_browser_visit():
    result = _event_summary("browser_visit", {"domain": "github.com"})
    assert "github.com" in result


def test_event_summary_browser_search():
    result = _event_summary("browser_search", {"query_length": 15})
    assert "15 chars" in result


def test_event_summary_browser_copy():
    result = _event_summary("browser_copy", {"text_length": 200})
    assert "200 chars" in result


def test_event_summary_browser_ai_chat():
    result = _event_summary("browser_ai_chat", {"platform": "ChatGPT"})
    assert "ChatGPT" in result


def test_event_summary_inline_completion():
    result = _event_summary("inline_completion_shown", {"path": "main.py", "language": "python"})
    assert "main.py" in result
    assert "python" in result


def test_event_summary_fallback():
    result = _event_summary("unknown_type", {"key1": "val1", "key2": "val2"})
    assert "key1=val1" in result


def test_event_summary_empty():
    result = _event_summary("unknown_type", {})
    assert result == ""


# ── view ──


def test_view_no_events(make_session, capsys):
    sid, _ = make_session(n_events=0)
    session = store.get_session(sid)
    view(session)
    assert "No events captured" in capsys.readouterr().out


def test_view_with_events(make_session, capsys):
    sid, events = make_session(n_events=5)
    session = store.get_session(sid)
    view(session)
    out = capsys.readouterr().out
    assert "5 events" in out
    assert "Total:" in out
    assert "methodproof push" in out


def test_view_shows_sensitive_fields(capsys):
    sid = uuid.uuid4().hex
    store.create_session(sid, "/tmp")
    events = [{
        "id": uuid.uuid4().hex,
        "type": "terminal_cmd",
        "timestamp": time.time(),
        "metadata": {"command": "ls -la", "output_snippet": "total 42"},
    }]
    store.insert_events(sid, events)
    store.complete_session(sid)
    session = store.get_session(sid)
    view(session)
    out = capsys.readouterr().out
    assert "sensitive (encrypted)" in out
