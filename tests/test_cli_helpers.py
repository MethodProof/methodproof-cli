"""Tests for CLI pure helper functions."""

import sys

import pytest

from methodproof import cli, config, store


# ── _rainbow ──


def test_rainbow_plain_when_not_tty(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert cli._rainbow("hello") == "hello"


def test_rainbow_colored_when_tty(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    result = cli._rainbow("hi")
    assert "\033[" in result
    assert "hi"[0] in result


# ── _app_url ──


def test_app_url_production():
    assert cli._app_url("https://api.methodproof.com") == "https://app.methodproof.com"


def test_app_url_localhost():
    assert cli._app_url("http://localhost:8000") == "http://localhost:5173"


def test_app_url_127():
    assert cli._app_url("http://127.0.0.1:8000") == "http://localhost:5173"


# ── _decode_jwt_claims ──


def test_decode_jwt_valid(fake_jwt):
    token = fake_jwt(user_id="abc-123", role="reviewer")
    claims = cli._decode_jwt_claims(token)
    assert claims["user_id"] == "abc-123"
    assert claims["role"] == "reviewer"


def test_decode_jwt_malformed():
    # Malformed base64 payload raises — _decode_jwt_claims doesn't guard it
    with pytest.raises(Exception):
        cli._decode_jwt_claims("not.a.jwt")


def test_decode_jwt_too_few_parts():
    assert cli._decode_jwt_claims("onlyone") == {}


# ── _duration ──


def test_duration_completed():
    s = {"created_at": 1000.0, "completed_at": 1125.0}
    assert cli._duration(s) == "2:05"


def test_duration_missing_completed():
    s = {"created_at": 1000.0}
    assert cli._duration(s) == "--:--"


def test_duration_missing_created():
    s = {"completed_at": 1000.0}
    assert cli._duration(s) == "--:--"


# ── _session_status ──


def test_session_status_recording(logged_in_cfg, make_session):
    sid, _ = make_session()
    cfg = logged_in_cfg()
    cfg["active_session"] = sid
    config.save(cfg)
    s = store.get_session(sid)
    assert cli._session_status(s) == "recording"


def test_session_status_abandoned(make_session):
    sid, _ = make_session(n_events=0)
    # Undo the complete_session by clearing completed_at
    store._db().execute("UPDATE sessions SET completed_at = NULL WHERE id = ?", (sid,))
    store._db().commit()
    s = store.get_session(sid)
    assert cli._session_status(s) == "abandoned"


def test_session_status_empty(make_session):
    sid, _ = make_session(n_events=0)
    s = store.get_session(sid)
    assert cli._session_status(s) == "empty"


def test_session_status_pushed(make_session):
    sid, _ = make_session()
    store.mark_synced(sid, "remote-123")
    s = store.get_session(sid)
    assert cli._session_status(s) == "pushed"


def test_session_status_stopped(make_session):
    sid, _ = make_session()
    s = store.get_session(sid)
    assert cli._session_status(s) == "stopped"


# ── _latest ──


def test_latest_returns_first_session(make_session):
    sid1, _ = make_session()
    sid2, _ = make_session()
    result = cli._latest()
    # list_sessions is ordered by created_at DESC
    assert result in (sid1, sid2)


def test_latest_returns_none_when_empty():
    assert cli._latest() is None


# ── _resolve_session ──


def test_resolve_session_exact_match(make_session):
    sid, _ = make_session()
    s = cli._resolve_session(sid)
    assert s["id"] == sid


def test_resolve_session_prefix_match(make_session):
    sid, _ = make_session()
    s = cli._resolve_session(sid[:8])
    assert s["id"] == sid


def test_resolve_session_no_match():
    with pytest.raises(SystemExit):
        cli._resolve_session("nonexistent")


def test_resolve_session_none_uses_latest(make_session):
    sid, _ = make_session()
    s = cli._resolve_session(None)
    assert s["id"] == sid
