"""Tests for live streaming — WebSocket handshake and event forwarding."""

import json
import queue
import threading
from unittest.mock import MagicMock, patch

import pytest

from methodproof import live


@pytest.fixture(autouse=True)
def reset_live_state():
    """Reset module-level state between tests."""
    live._ws = None
    live._connected.clear()
    live._stop.clear()
    # Drain the queue
    while not live._send_queue.empty():
        try:
            live._send_queue.get_nowait()
        except queue.Empty:
            break
    yield
    live.stop()


def _mock_ws(ready_reply: dict | None = None):
    """Create a mock websocket with configurable handshake reply."""
    ws = MagicMock()
    reply = ready_reply or {"type": "ready", "url": "https://app.methodproof.com/personal/sessions/abc123"}
    ws.recv.return_value = json.dumps(reply)
    return ws


FULL_CONSENT = {
    "terminal_commands": True, "command_output": True, "test_results": True,
    "file_changes": True, "git_commits": True, "ai_prompts": True,
    "ai_responses": True, "browser": True, "music": True,
}


@patch("websocket.create_connection")
def test_start_returns_url_on_success(mock_create):
    """Successful handshake returns the dashboard URL."""
    url = "https://app.methodproof.com/personal/sessions/test-session-id"
    mock_create.return_value = _mock_ws({"type": "ready", "url": url})

    result = live.start("https://api.methodproof.com", "token", "test-session-id", FULL_CONSENT)

    assert result == url
    assert live._connected.is_set()


@patch("websocket.create_connection")
def test_start_returns_none_on_rejection(mock_create):
    """Rejected handshake returns None."""
    mock_create.return_value = _mock_ws({"type": "error", "detail": "Tier insufficient"})

    result = live.start("https://api.methodproof.com", "token", "sid", FULL_CONSENT)

    assert result is None
    assert not live._connected.is_set()


@patch("websocket.create_connection")
def test_start_sends_correct_handshake(mock_create):
    """Handshake sends consent config as JSON."""
    ws = _mock_ws()
    mock_create.return_value = ws

    live.start("https://api.methodproof.com", "tok", "sid", FULL_CONSENT)

    # Verify handshake message
    sent = json.loads(ws.send.call_args[0][0])
    assert sent["type"] == "handshake"
    assert sent["consent"] == FULL_CONSENT


@patch("websocket.create_connection")
def test_start_constructs_wss_url(mock_create):
    """HTTPS API URL is converted to WSS for WebSocket."""
    mock_create.return_value = _mock_ws()

    live.start("https://api.methodproof.com", "tok", "my-session", FULL_CONSENT)

    call_url = mock_create.call_args[0][0]
    assert call_url == "wss://api.methodproof.com/sessions/my-session/stream?token=tok"


@patch("websocket.create_connection")
def test_start_constructs_ws_url_for_http(mock_create):
    """HTTP API URL is converted to WS for local dev."""
    mock_create.return_value = _mock_ws()

    live.start("http://localhost:8000", "tok", "sid", FULL_CONSENT)

    call_url = mock_create.call_args[0][0]
    assert call_url == "ws://localhost:8000/sessions/sid/stream?token=tok"


@patch("websocket.create_connection")
def test_send_queues_event(mock_create):
    """send() queues events when connected."""
    mock_create.return_value = _mock_ws()
    live.start("https://api.methodproof.com", "tok", "sid", FULL_CONSENT)

    event = {"id": "abc", "type": "terminal_cmd", "timestamp": 123.0}
    live.send(event)

    msg = live._send_queue.get_nowait()
    parsed = json.loads(msg)
    assert parsed["id"] == "abc"
    assert parsed["type"] == "terminal_cmd"


def test_send_drops_when_disconnected():
    """send() silently drops events when not connected."""
    event = {"id": "abc", "type": "terminal_cmd"}
    live.send(event)

    assert live._send_queue.empty()


@patch("websocket.create_connection")
def test_stop_clears_state(mock_create):
    """stop() clears connected flag and closes WebSocket."""
    ws = _mock_ws()
    mock_create.return_value = ws
    live.start("https://api.methodproof.com", "tok", "sid", FULL_CONSENT)

    assert live._connected.is_set()
    live.stop()

    assert not live._connected.is_set()
    ws.close.assert_called_once()
    assert live._ws is None


@patch("websocket.create_connection")
def test_start_empty_url_fallback(mock_create):
    """If server sends ready without url, returns empty string."""
    mock_create.return_value = _mock_ws({"type": "ready"})

    result = live.start("https://api.methodproof.com", "tok", "sid", FULL_CONSENT)

    assert result == ""
