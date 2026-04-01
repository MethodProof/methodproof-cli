"""Tests for SQLite store."""

import time
import uuid
from pathlib import Path

import pytest

from methodproof import config, store


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "_conn", None)
    store.init_db()


def test_init_creates_tables() -> None:
    db = store._db()
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "sessions" in tables
    assert "events" in tables
    assert "next_chain" in tables
    assert "causal_links" in tables


def test_create_and_get_session() -> None:
    sid = uuid.uuid4().hex
    store.create_session(sid, "/tmp/test")
    s = store.get_session(sid)
    assert s is not None
    assert s["watch_dir"] == "/tmp/test"
    assert s["total_events"] == 0
    assert s["synced"] == 0


def test_insert_events_and_count() -> None:
    sid = uuid.uuid4().hex
    store.create_session(sid, "/tmp")
    events = [
        {"id": uuid.uuid4().hex, "type": "file_edit",
         "timestamp": time.time(), "duration_ms": 100,
         "metadata": {"path": "a.py"}},
        {"id": uuid.uuid4().hex, "type": "terminal_cmd",
         "timestamp": time.time() + 1, "duration_ms": 50,
         "metadata": {"command": "ls"}},
    ]
    store.insert_events(sid, events)
    store.complete_session(sid)
    s = store.get_session(sid)
    assert s["total_events"] == 2


def test_list_sessions_ordered() -> None:
    store.create_session("a", "/a")
    time.sleep(0.01)
    store.create_session("b", "/b")
    sessions = store.list_sessions()
    assert sessions[0]["id"] == "b"  # newest first


def test_get_events_sorted() -> None:
    sid = uuid.uuid4().hex
    store.create_session(sid, "/tmp")
    store.insert_events(sid, [
        {"id": "e2", "type": "x", "timestamp": 200, "metadata": {}},
        {"id": "e1", "type": "x", "timestamp": 100, "metadata": {}},
    ])
    events = store.get_events(sid)
    assert events[0]["id"] == "e1"
    assert events[1]["id"] == "e2"


def test_mark_synced() -> None:
    sid = uuid.uuid4().hex
    store.create_session(sid, "/tmp")
    store.mark_synced(sid, "remote-123")
    s = store.get_session(sid)
    assert s["synced"] == 1
    assert s["remote_id"] == "remote-123"


def test_idempotent_init() -> None:
    store.init_db()
    store.init_db()  # should not raise


def test_duplicate_event_ignored() -> None:
    sid = uuid.uuid4().hex
    store.create_session(sid, "/tmp")
    event = {"id": "dup", "type": "x", "timestamp": 100, "metadata": {}}
    store.insert_events(sid, [event])
    store.insert_events(sid, [event])  # duplicate — ignored
    assert len(store.get_events(sid)) == 1
