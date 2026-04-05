"""Local HTTP bridge — accepts browser extension events into SQLite and handles pairing."""

import json
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from methodproof import store
from methodproof.agents import base

_session_id = ""
_api_token = ""
_api_base = ""
_e2e_key = ""
_pairing: dict[str, Any] = {}  # {token: {session_id, api_token, api_base, e2e_key, paired}}
_extension_paired = threading.Event()
MAX_BODY = 10 * 1024 * 1024  # 10 MB

PAIR_PAGE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>MethodProof — Pair Extension</title>
  <style>
    body {{ font-family: Inter, system-ui, sans-serif; background: #faf9f7; color: #0a0a0a;
           display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }}
    .card {{ text-align: center; padding: 48px; max-width: 400px; }}
    h1 {{ font-size: 18px; margin: 0 0 8px; }}
    h1 span {{ font-family: Laila, serif; font-weight: 400; }}
    .status {{ font-size: 14px; color: #666; margin: 24px 0; }}
    .paired {{ color: #2d7a42; font-weight: 600; }}
    .session {{ font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: #888;
               background: #f0eeea; padding: 8px 12px; display: inline-block; }}
    .spinner {{ display: inline-block; width: 16px; height: 16px; border: 2px solid #ddd;
               border-top-color: #d93326; border-radius: 50%; animation: spin 0.8s linear infinite;
               vertical-align: middle; margin-right: 8px; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  </style>
</head>
<body>
  <div class="card">
    <h1><b>Method</b><span>Proof</span></h1>
    <div class="session">{session_short}</div>
    <div id="status" class="status"><span class="spinner"></span>Pairing extension...</div>
    <div id="methodproof-pair-data"
         data-session-id="{session_id}"
         data-token="{api_token}"
         data-api-base="{api_base}"
         data-e2e-key="{e2e_key}"
         style="display:none"></div>
  </div>
  <script>
    window.addEventListener('methodproof-paired', function() {{
      document.getElementById('status').className = 'status paired';
      document.getElementById('status').innerHTML = '&#10003; Extension paired';
      fetch('/pair/ack', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{token: '{pair_token}'}}) }});
      setTimeout(function() {{ window.close(); }}, 2000);
    }});
  </script>
</body>
</html>"""


def generate_pair_token(session_id: str, api_token: str, api_base: str, e2e_key: str = "") -> str:
    token = secrets.token_urlsafe(16)
    _pairing[token] = {
        "session_id": session_id, "api_token": api_token,
        "api_base": api_base, "e2e_key": e2e_key, "paired": False,
    }
    return token


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/session":
            self._json({"session_id": _session_id, "active": bool(_session_id)})
        elif self.path.startswith("/pair?token="):
            token = self.path.split("token=", 1)[1].split("&")[0]
            data = _pairing.get(token)
            if not data:
                self.send_error(403, "Invalid or expired pairing token")
                return
            html = PAIR_PAGE.format(
                session_id=data["session_id"],
                session_short=data["session_id"][:8],
                api_token=data["api_token"],
                api_base=data["api_base"],
                e2e_key=data["e2e_key"],
                pair_token=token,
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self._cors()
            self.end_headers()
            self.wfile.write(html)
        elif self.path == "/pair/auto":
            if not _session_id:
                self._json({"active": False})
            else:
                self._json({
                    "active": True,
                    "session_id": _session_id,
                    "token": _api_token,
                    "api_base": _api_base,
                    "e2e_key": _e2e_key,
                })
                _extension_paired.set()
                base.log("info", "extension.auto_paired", session_id=_session_id)
        elif self.path == "/extension-status":
            self._json({"paired": _extension_paired.is_set()})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY:
            self.send_error(413, "Request too large")
            return
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except (json.JSONDecodeError, ValueError):
            self.send_error(400, "Invalid JSON")
            return

        if self.path == "/events":
            events = body.get("events", [])
            for e in events:
                e.setdefault("id", uuid.uuid4().hex)
                e.setdefault("timestamp", time.time())
                e.setdefault("duration_ms", 0)
                e.setdefault("metadata", e.get("metadata", {}))
            accepted = 0
            if events:
                try:
                    store.insert_events(_session_id, events)
                    accepted = len(events)
                except Exception:
                    self.send_error(500, "Storage error")
                    return
            self._json({"accepted": accepted})
        elif self.path == "/pair/register":
            token = body.get("token", "")
            if not token or not body.get("session_id"):
                self.send_error(400, "Missing token or session_id")
                return
            _pairing[token] = {
                "session_id": body["session_id"],
                "api_token": body.get("api_token", ""),
                "api_base": body.get("api_base", ""),
                "e2e_key": body.get("e2e_key", ""),
                "paired": False,
            }
            self._json({"ok": True, "token": token})
        elif self.path == "/pair/ack":
            token = body.get("token", "")
            data = _pairing.get(token)
            if data:
                data["paired"] = True
                _extension_paired.set()
                base.log("info", "extension.paired", session_id=data["session_id"])
            self._json({"ok": bool(data)})
        else:
            self.send_error(404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _json(self, data: Any) -> None:
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        allowed = origin.startswith("chrome-extension://") or origin.startswith("http://localhost")
        self.send_header("Access-Control-Allow-Origin", origin if allowed else "http://localhost:9877")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def start(session_id: str, stop: threading.Event, port: int = 9877,
          api_token: str = "", api_base: str = "", e2e_key: str = "") -> None:
    global _session_id, _api_token, _api_base, _e2e_key
    _session_id = session_id
    _api_token = api_token
    _api_base = api_base
    _e2e_key = e2e_key
    _extension_paired.clear()
    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("127.0.0.1", port), _Handler)
    server.timeout = 1
    base.log("info", "bridge.started", port=port)
    while not stop.is_set():
        server.handle_request()
    server.server_close()
    base.log("info", "bridge.stopped")
