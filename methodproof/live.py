"""Live streaming — WebSocket client that forwards events to platform."""

import json
import queue
import threading
import time
from typing import Any

_ws = None
_send_queue: queue.Queue[str] = queue.Queue(maxsize=500)
_connected = threading.Event()
_stop = threading.Event()


def _detect_layers() -> dict[str, bool]:
    """Detect which capture layers are active on this machine."""
    import shutil
    from pathlib import Path

    layers: dict[str, bool] = {}

    # Hooks installed?
    from methodproof.hooks.install import is_installed as claude_installed
    layers["hooks_claude"] = claude_installed()

    # Check for other tool hook configs
    layers["hooks_codex"] = (Path.home() / ".codex" / "hooks.json").exists()
    layers["hooks_gemini"] = (Path.home() / ".gemini" / "settings.json").exists()
    layers["hooks_kiro"] = (Path.home() / ".kiro" / "hooks.json").exists()

    # CLI wrappers installed?
    from methodproof.hooks.wrappers import is_installed as wrappers_installed
    layers["wrappers"] = wrappers_installed()

    # MCP registrations (check at least one)
    mcp_paths = [
        Path.home() / ".cursor" / "mcp.json",
        Path.home() / ".roo" / "mcp.json",
        Path.home() / ".junie" / "mcp" / "mcp.json",
    ]
    layers["mcp"] = any(
        p.exists() and "methodproof" in p.read_text()
        for p in mcp_paths if p.exists()
    )

    # Browser extension paired?
    from methodproof import config
    cfg = config.load()
    layers["extension"] = bool(cfg.get("extension_paired"))

    # Proxy active?
    proxy_pid = config.DIR / "proxy.pid"
    layers["proxy"] = proxy_pid.exists()

    return layers


def start(api_url: str, token: str, session_id: str, consent: dict[str, bool]) -> str | None:
    """Connect to platform WebSocket, perform handshake. Returns live URL or None."""
    import websocket  # websocket-client

    ws_url = api_url.replace("https://", "wss://").replace("http://", "ws://")
    url = f"{ws_url}/sessions/{session_id}/stream?token={token}"

    global _ws
    _ws = websocket.create_connection(url, timeout=10)

    # Handshake — send consent + installed capture layers
    layers = _detect_layers()
    _ws.send(json.dumps({"type": "handshake", "consent": consent, "layers": layers}))
    reply = json.loads(_ws.recv())

    if reply.get("type") != "ready":
        detail = reply.get("detail", "rejected")
        _ws.close()
        _ws = None
        from methodproof.agents.base import log
        log("error", "live.rejected", detail=detail)
        return None

    _connected.set()
    threading.Thread(target=_sender_loop, daemon=True).start()
    return reply.get("url", "")


def send(event: dict[str, Any]) -> None:
    """Queue an event for live broadcast. Drops silently if queue is full."""
    if not _connected.is_set():
        return
    try:
        _send_queue.put_nowait(json.dumps(event, default=str))
    except queue.Full:
        pass


def stop() -> None:
    """Disconnect gracefully."""
    _stop.set()
    _connected.clear()
    global _ws
    if _ws:
        try:
            _ws.close()
        except Exception:
            pass
        _ws = None


def _sender_loop() -> None:
    """Drain the queue and send over WebSocket."""
    while not _stop.is_set():
        try:
            msg = _send_queue.get(timeout=1)
        except queue.Empty:
            continue
        try:
            if _ws:
                _ws.send(msg)
        except Exception:
            _connected.clear()
            from methodproof.agents.base import log
            log("warning", "live.send_failed")
            break
