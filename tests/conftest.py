"""Shared fixtures for CLI tests."""

import argparse
import base64
import json
import time
import uuid
import zlib
from pathlib import Path
from typing import Any

import pytest

from methodproof import config, store


# ── Filesystem isolation ──


@pytest.fixture(autouse=True)
def isolate_fs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate all config/DB/log paths to tmp_path. Writes defaults to disk
    so config.load() always parses JSON (avoids _DEFAULTS shallow-copy mutation)."""
    mp_dir = tmp_path / ".methodproof"
    mp_dir.mkdir()
    monkeypatch.setattr(config, "DIR", mp_dir)
    monkeypatch.setattr(config, "CONFIG", mp_dir / "config.json")
    monkeypatch.setattr(config, "DB_PATH", mp_dir / "methodproof.db")
    monkeypatch.setattr(config, "CMD_LOG", mp_dir / "commands.jsonl")
    defaults = {**config._DEFAULTS, "ui_mode": False}
    (mp_dir / "config.json").write_text(json.dumps(defaults, indent=2))
    monkeypatch.setattr(store, "_conn", None)
    store.init_db()
    return tmp_path


# ── JWT helper ──


@pytest.fixture
def fake_jwt():
    """Factory: builds a real base64-encoded JWT so _decode_jwt_claims works."""
    def _make(
        user_id: str = "test-account-123",
        role: str = "admin",
        account_type: str = "pro",
        exp: float | None = None,
        **extra: Any,
    ) -> str:
        header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
        claims = {
            "user_id": user_id,
            "role": role,
            "account_type": account_type,
            "exp": exp if exp is not None else time.time() + 3600,
            **extra,
        }
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
        return f"{header}.{payload}.{sig}"
    return _make


# ── Config helpers ──


@pytest.fixture
def logged_in_cfg(fake_jwt):
    """Factory: writes a config with valid auth state, returns cfg dict."""
    def _make(
        account_id: str = "test-account-123",
        email: str = "test@methodproof.com",
        token: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        cfg = config.load()
        cfg["token"] = token or fake_jwt(user_id=account_id)
        cfg["account_id"] = account_id
        cfg["email"] = email
        cfg["last_auth_at"] = time.time()
        cfg.update(extra)
        config.save(cfg)
        return cfg
    return _make


# ── Session factory ──


@pytest.fixture
def make_session():
    """Factory: creates a completed session with N events in SQLite."""
    def _make(n_events: int = 5, account_id: str = "test-account-123",
              watch_dir: str = "/tmp/test", **session_kwargs: Any) -> tuple[str, list[dict]]:
        sid = uuid.uuid4().hex
        store.create_session(sid, watch_dir, account_id=account_id, **session_kwargs)
        events = []
        base_ts = time.time() - 300
        for i in range(n_events):
            e = {
                "id": uuid.uuid4().hex,
                "type": ["file_edit", "terminal_cmd", "llm_prompt", "git_commit", "test_run"][i % 5],
                "timestamp": base_ts + i * 10,
                "duration_ms": 100 + i * 50,
                "metadata": {"path": f"file_{i}.py", "language": "python"},
            }
            events.append(e)
        store.insert_events(sid, events)
        store.complete_session(sid)
        return sid, events
    return _make


# ── Argparse helper ──


@pytest.fixture
def cli_args():
    """Factory: builds argparse.Namespace with sensible defaults."""
    def _make(**kwargs: Any) -> argparse.Namespace:
        defaults = {
            "session_id": None, "dir": None, "repo": None, "tags": None,
            "public": False, "live": False, "live_public": False,
            "journal": False, "e2e": False, "no_e2e": False,
            "verbose": False, "streaming": False, "force": False,
            "local": False, "api_url": None, "no_key": False, "auto": None,
            "account": None, "purge": False, "keep_sessions": False,
            "anonymous": False,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)
    return _make
