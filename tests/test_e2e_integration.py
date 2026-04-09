"""E2E integration tests — full CLI flows against local API.

Requires: just infra-up && just seed && just platform
Run with: pytest -m e2e
"""

import json
import os
import time
import urllib.error
import urllib.request

import pytest

from methodproof import cli, config, store

pytestmark = pytest.mark.e2e

API_URL = "http://localhost:8000"


# ── Fixtures ──


def _api_available() -> bool:
    try:
        urllib.request.urlopen(f"{API_URL}/health", timeout=2)
        return True
    except Exception:
        return False


def _login(email: str, password: str) -> dict:
    """Login via API and return {token, refresh_token, user_id}."""
    body = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        f"{API_URL}/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


@pytest.fixture(autouse=True)
def require_api():
    if not _api_available():
        pytest.skip("Local API not running (need: just infra-up && just seed && just platform)")


@pytest.fixture
def pro_auth() -> dict:
    """Login as the pro seed user, configure CLI."""
    result = _login("pro@methodproof.com", "methodproof123")
    cfg = config.load()
    cfg["token"] = result["token"]
    cfg["refresh_token"] = result.get("refresh_token", "")
    cfg["account_id"] = result.get("user_id", "")
    cfg["email"] = "pro@methodproof.com"
    cfg["api_url"] = API_URL
    cfg["last_auth_at"] = time.time()
    config.save(cfg)
    return result


@pytest.fixture
def free_auth() -> dict:
    """Login as the free seed user."""
    result = _login("free@methodproof.com", "methodproof123")
    cfg = config.load()
    cfg["token"] = result["token"]
    cfg["refresh_token"] = result.get("refresh_token", "")
    cfg["account_id"] = result.get("user_id", "")
    cfg["email"] = "free@methodproof.com"
    cfg["api_url"] = API_URL
    cfg["last_auth_at"] = time.time()
    config.save(cfg)
    return result


def _api_get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{API_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ── Tests ──


def test_status_shows_logged_in(pro_auth, cli_args, capsys):
    cli.cmd_status(cli_args())
    out = capsys.readouterr().out
    assert "signed in" in out


def test_push_and_verify_on_platform(pro_auth, make_session, cli_args, capsys):
    sid, _ = make_session(n_events=3)
    cfg = config.load()
    from methodproof.sync import push
    remote_id = push(sid, cfg["token"], API_URL)
    assert remote_id
    # Verify on platform
    result = _api_get(f"/personal/sessions/{remote_id}", cfg["token"])
    assert result["session_id"] == remote_id


def test_push_then_publish(pro_auth, make_session, cli_args, capsys):
    sid, _ = make_session(n_events=3)
    cfg = config.load()
    from methodproof.sync import push
    remote_id = push(sid, cfg["token"], API_URL)
    # Publish
    store.update_visibility(sid, "public")
    session = store.get_session(sid)
    from methodproof.sync import sync_metadata
    sync_metadata(session, cfg["token"], API_URL)
    # Verify
    result = _api_get(f"/personal/sessions/{remote_id}", cfg["token"])
    assert result.get("visibility") == "public"


def test_tag_then_push(pro_auth, make_session, cli_args, capsys):
    sid, _ = make_session(n_events=3)
    store.update_tags(sid, ["e2e-test", "python"])
    cfg = config.load()
    from methodproof.sync import push
    remote_id = push(sid, cfg["token"], API_URL)
    result = _api_get(f"/personal/sessions/{remote_id}", cfg["token"])
    assert "e2e-test" in result.get("tags", [])


def test_multi_account_switch(pro_auth, free_auth, cli_args, capsys):
    # Login as pro first
    pro_cfg = config.load()
    pro_cfg["token"] = pro_auth["token"]
    pro_cfg["account_id"] = pro_auth.get("user_id", "")
    pro_cfg["email"] = "pro@methodproof.com"
    pro_cfg["api_url"] = API_URL
    config.save(pro_cfg)
    config.save_active_profile(pro_cfg)

    # Switch to free
    free_cfg = config.load()
    free_cfg["account_id"] = free_auth.get("user_id", "")
    free_cfg["token"] = free_auth["token"]
    free_cfg["email"] = "free@methodproof.com"
    config.save(free_cfg)
    config.save_active_profile(free_cfg)

    # Switch back to pro
    pro_id = pro_auth.get("user_id", "")
    config.restore_profile(free_cfg, pro_id)
    final = config.load()
    assert final["email"] == "pro@methodproof.com"
    assert final["token"] == pro_auth["token"]
