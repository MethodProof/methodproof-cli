"""Tests for graph builder — NEXT chain + causal links."""

import json
import time
import uuid
from pathlib import Path

import pytest

from methodproof import config, store, graph


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "_conn", None)
    store.init_db()


def _session(events: list[dict]) -> str:
    sid = uuid.uuid4().hex
    store.create_session(sid, "/tmp")
    store.insert_events(sid, events)
    return sid


def _event(etype: str, ts: float, meta: dict | None = None) -> dict:
    return {"id": uuid.uuid4().hex, "type": etype, "timestamp": ts,
            "duration_ms": 0, "metadata": meta or {}}


def test_next_chain_basic() -> None:
    sid = _session([
        _event("terminal_cmd", 100),
        _event("file_edit", 105),
        _event("file_edit", 110),
    ])
    stats = graph.build(sid)
    assert stats["next"] == 2

    db = store._db()
    rows = db.execute("SELECT * FROM next_chain").fetchall()
    assert len(rows) == 2


def test_received_link() -> None:
    """prompt → completion, same model, within 60s."""
    sid = _session([
        _event("llm_prompt", 100, {"model": "claude", "prompt_text": "hi",
               "token_count": 10, "temperature": 0.7, "tools_available": []}),
        _event("llm_completion", 108, {"model": "claude", "response_text": "hello",
               "token_count": 50, "finish_reason": "stop", "latency_ms": 800}),
    ])
    stats = graph.build(sid)
    assert stats["causal"] >= 1

    db = store._db()
    links = db.execute("SELECT * FROM causal_links WHERE type = 'RECEIVED'").fetchall()
    assert len(links) == 1


def test_no_received_different_model() -> None:
    sid = _session([
        _event("llm_prompt", 100, {"model": "claude"}),
        _event("llm_completion", 108, {"model": "gpt-4"}),
    ])
    graph.build(sid)
    db = store._db()
    assert db.execute("SELECT count(*) FROM causal_links WHERE type='RECEIVED'").fetchone()[0] == 0


def test_informed_link() -> None:
    """completion → file_edit within 60s."""
    sid = _session([
        _event("llm_completion", 100, {"model": "claude"}),
        _event("file_edit", 130, {"path": "a.py"}),
    ])
    stats = graph.build(sid)
    assert stats["causal"] >= 1

    db = store._db()
    assert db.execute("SELECT count(*) FROM causal_links WHERE type='INFORMED'").fetchone()[0] == 1


def test_led_to_link() -> None:
    """search → visit within 120s."""
    sid = _session([
        _event("web_search", 100, {"query": "flask"}),
        _event("web_visit", 150, {"url": "https://flask.dev", "domain": "flask.dev"}),
    ])
    graph.build(sid)
    db = store._db()
    assert db.execute("SELECT count(*) FROM causal_links WHERE type='LED_TO'").fetchone()[0] == 1


def test_no_link_outside_window() -> None:
    """completion → edit >60s apart → no INFORMED."""
    sid = _session([
        _event("llm_completion", 100, {"model": "claude"}),
        _event("file_edit", 200, {"path": "a.py"}),  # 100s gap
    ])
    graph.build(sid)
    db = store._db()
    assert db.execute("SELECT count(*) FROM causal_links WHERE type='INFORMED'").fetchone()[0] == 0


def test_resource_creation() -> None:
    sid = _session([
        _event("llm_prompt", 100, {"model": "claude-sonnet"}),
    ])
    graph.build(sid)
    db = store._db()
    assert db.execute("SELECT count(*) FROM resources WHERE identifier='claude-sonnet'").fetchone()[0] == 1


def test_artifact_creation() -> None:
    sid = _session([
        _event("file_create", 100, {"path": "src/main.py", "size": 500, "language": "python"}),
    ])
    graph.build(sid)
    db = store._db()
    assert db.execute("SELECT count(*) FROM artifacts WHERE path='src/main.py'").fetchone()[0] == 1


def test_build_returns_stats() -> None:
    sid = _session([_event("terminal_cmd", 100), _event("file_edit", 105)])
    stats = graph.build(sid)
    assert "next" in stats
    assert "causal" in stats
    assert "resources" in stats
    assert "artifacts" in stats
