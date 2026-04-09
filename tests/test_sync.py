"""Tests for sync.py — HTTP push, token refresh, metadata sync."""

import gzip
import json
import time
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from methodproof import config, store
from methodproof.sync import (
    _iso, _raw_request, _refresh_token, _request, push, sync_metadata,
    sync_research_consent,
)


# ── Helpers ──


def _mock_urlopen(response_data: dict, status: int = 200):
    """Create a mock for urllib.request.urlopen that returns JSON."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response_data).encode()
    mock_resp.status = status
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _mock_http_error(code: int, detail: str = ""):
    body = json.dumps({"detail": detail}).encode() if detail else b""
    exc = urllib.error.HTTPError(
        url="http://test", code=code, msg="",
        hdrs=MagicMock(), fp=BytesIO(body),
    )
    return exc


# ── _iso ──


def test_iso_converts_timestamp():
    result = _iso(0.0)
    assert "1970-01-01" in result
    assert result.endswith("+00:00")


def test_iso_recent_timestamp():
    result = _iso(1712000000.0)
    assert "2024-04-" in result


# ── _raw_request ──


@patch("urllib.request.urlopen")
def test_raw_request_get(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen({"ok": True})
    result = _raw_request("GET", "http://api/test", "tok-123")
    assert result == {"ok": True}
    req = mock_urlopen.call_args[0][0]
    assert req.method == "GET"
    assert req.data is None
    assert req.get_header("Authorization") == "Bearer tok-123"


@patch("urllib.request.urlopen")
def test_raw_request_post_gzips_body(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen({"id": "abc"})
    result = _raw_request("POST", "http://api/test", "tok", body={"foo": "bar"})
    assert result == {"id": "abc"}
    req = mock_urlopen.call_args[0][0]
    assert req.get_header("Content-encoding") == "gzip"
    decompressed = json.loads(gzip.decompress(req.data))
    assert decompressed == {"foo": "bar"}


# ── _refresh_token ──


@patch("urllib.request.urlopen")
def test_refresh_token_success(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen({
        "access_token": "new-access", "refresh_token": "new-refresh",
    })
    result = _refresh_token("http://api", "old-refresh")
    assert result == ("new-access", "new-refresh")


@patch("urllib.request.urlopen")
def test_refresh_token_failure(mock_urlopen):
    mock_urlopen.side_effect = Exception("network error")
    result = _refresh_token("http://api", "bad-refresh")
    assert result is None


# ── _request ──


@patch("urllib.request.urlopen")
def test_request_success(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen({"data": "ok"})
    result = _request("GET", "/test", "http://api", "tok")
    assert result == {"data": "ok"}


@patch("urllib.request.urlopen")
def test_request_401_with_refresh(mock_urlopen):
    # First call: 401, second call (refresh): success, third call (retry): success
    mock_urlopen.side_effect = [
        _mock_http_error(401),
        _mock_urlopen({"access_token": "new", "refresh_token": "new-r"}),
        _mock_urlopen({"retried": True}),
    ]
    cfg = config.load()
    cfg["refresh_token"] = "old-refresh"
    config.save(cfg)
    result = _request("GET", "/test", "http://api", "tok")
    assert result == {"retried": True}


@patch("urllib.request.urlopen")
def test_request_401_no_refresh_exits(mock_urlopen):
    mock_urlopen.side_effect = _mock_http_error(401)
    cfg = config.load()
    cfg["refresh_token"] = ""
    config.save(cfg)
    with pytest.raises(SystemExit, match="Session expired"):
        _request("GET", "/test", "http://api", "tok")


@patch("urllib.request.urlopen")
def test_request_500_exits_with_detail(mock_urlopen):
    mock_urlopen.side_effect = _mock_http_error(500, "Internal server error")
    with pytest.raises(SystemExit, match="API error 500.*Internal server error"):
        _request("GET", "/fail", "http://api", "tok")


# ── push ──


@patch("methodproof.sync._request")
def test_push_session_not_found(mock_req):
    with pytest.raises(SystemExit, match="Session not found"):
        push("nonexistent", "tok", "http://api")


@patch("methodproof.sync._request")
def test_push_already_synced(mock_req, make_session, capsys):
    sid, _ = make_session()
    store.mark_synced(sid, "remote-abc")
    result = push(sid, "tok", "http://api")
    assert result == "remote-abc"
    assert "Already synced" in capsys.readouterr().out


@patch("methodproof.sync._request")
@patch("methodproof.integrity.has_keypair", return_value=False)
def test_push_happy_path(mock_keypair, mock_req, make_session, capsys):
    sid, events = make_session(n_events=3)
    mock_req.side_effect = [
        {"session_id": "remote-xyz"},  # POST /personal/sessions
        {"ok": True},                  # POST /sessions/remote-xyz/events
        {"ok": True},                  # PUT /personal/sessions/remote-xyz/complete
    ]
    result = push(sid, "tok", "http://api")
    assert result == "remote-xyz"
    s = store.get_session(sid)
    assert s["synced"] == 1
    assert s["remote_id"] == "remote-xyz"


@patch("methodproof.sync._request")
@patch("methodproof.integrity.has_keypair", return_value=False)
@patch("time.sleep")
def test_push_429_retries(mock_sleep, mock_keypair, mock_req, make_session):
    sid, _ = make_session(n_events=2)
    mock_req.side_effect = [
        {"session_id": "remote-r"},       # create
        SystemExit("API error 429: rate limit"),  # first attempt
        {"ok": True},                     # retry
        {"ok": True},                     # complete
    ]
    result = push(sid, "tok", "http://api")
    assert result == "remote-r"
    mock_sleep.assert_called_once()


@patch("methodproof.sync._request")
@patch("methodproof.integrity.has_keypair", return_value=False)
def test_push_upload_failure_abandons(mock_keypair, mock_req, make_session):
    sid, _ = make_session(n_events=2)
    mock_req.side_effect = [
        {"session_id": "remote-fail"},
        SystemExit("API error 500: boom"),   # event upload
        {"ok": True},                        # abandon call
    ]
    with pytest.raises(SystemExit, match="500"):
        push(sid, "tok", "http://api")
    # Verify abandon was attempted (3rd call)
    assert mock_req.call_count == 3
    abandon_call = mock_req.call_args_list[2]
    assert "/abandon" in abandon_call[0][1]


# ── sync_metadata ──


@patch("methodproof.sync._request")
def test_sync_metadata_no_remote_id(mock_req):
    sync_metadata({"remote_id": None}, "tok", "http://api")
    mock_req.assert_not_called()


@patch("methodproof.sync._request")
def test_sync_metadata_full(mock_req):
    mock_req.return_value = {"ok": True}
    session = {
        "remote_id": "r-123",
        "repo_url": "https://github.com/test/repo",
        "tags": '["python", "ai"]',
        "visibility": "public",
    }
    sync_metadata(session, "tok", "http://api")
    assert mock_req.call_count == 3  # repos, tags, visibility


@patch("methodproof.sync._request")
def test_sync_metadata_private_skips_visibility(mock_req):
    mock_req.return_value = {"ok": True}
    session = {"remote_id": "r-123", "repo_url": None, "tags": "[]", "visibility": "private"}
    sync_metadata(session, "tok", "http://api")
    mock_req.assert_not_called()


# ── sync_research_consent ──


@patch("methodproof.sync._request")
def test_sync_research_consent_pulls_state(mock_req):
    mock_req.return_value = {"opt_in": True, "contribution_level": "enriched"}
    sync_research_consent("tok", "http://api")
    cfg = config.load()
    assert cfg["research_consent"] is True
    assert cfg["contribution_level"] == "enriched"


@patch("methodproof.sync._request")
def test_sync_research_consent_pushes_pending(mock_req):
    cfg = config.load()
    cfg["_pending_research_sync"] = True
    cfg["research_consent"] = True
    cfg["contribution_level"] = "structural"
    config.save(cfg)
    mock_req.return_value = {"opt_in": True, "contribution_level": "structural"}
    sync_research_consent("tok", "http://api")
    # First call should be PUT (push), second GET (pull)
    assert mock_req.call_count == 2
    cfg = config.load()
    assert cfg["_pending_research_sync"] is False


@patch("methodproof.sync._request")
def test_sync_research_consent_error_does_not_raise(mock_req):
    mock_req.side_effect = Exception("network down")
    sync_research_consent("tok", "http://api")  # should not raise
