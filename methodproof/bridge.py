"""Local HTTP bridge — accepts browser extension events into SQLite."""

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from methodproof import store
from methodproof.agents import base

_session_id = ""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/session":
            self._json({"session_id": _session_id, "active": bool(_session_id)})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/events":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            events = body.get("events", [])
            for e in events:
                e.setdefault("id", uuid.uuid4().hex)
                e.setdefault("timestamp", time.time())
                e.setdefault("duration_ms", 0)
                e.setdefault("metadata", e.get("metadata", {}))
            if events:
                store.insert_events(_session_id, events)
            self._json({"accepted": len(events)})
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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def start(session_id: str, stop: threading.Event, port: int = 9877) -> None:
    global _session_id
    _session_id = session_id
    server = HTTPServer(("127.0.0.1", port), _Handler)
    server.timeout = 1
    base.log("info", "bridge.started", port=port)
    while not stop.is_set():
        server.handle_request()
    server.server_close()
    base.log("info", "bridge.stopped")
