"""Push local sessions to the MethodProof platform."""

import json
import urllib.error
import urllib.request
from typing import Any

from methodproof import store


def _request(
    method: str, path: str, api_url: str, token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{api_url}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        if exc.fp:
            try:
                detail = json.loads(exc.read()).get("detail", "")
            except Exception:
                pass
        raise SystemExit(f"API error {exc.code}: {detail}") from None


def push(session_id: str, token: str, api_url: str) -> None:
    """Upload a local session to the platform."""
    session = store.get_session(session_id)
    if not session:
        raise SystemExit(f"Session not found: {session_id}")
    if session["synced"]:
        print(f"Already synced: {session_id[:8]}")
        return

    # Create remote session
    print("Creating remote session...", end=" ", flush=True)
    result = _request("POST", "/personal/sessions", api_url, token)
    remote_id = result["session_id"]
    print(f"done ({remote_id[:8]})")

    # Upload events in batches
    events = store.get_events(session_id)
    total = len(events)
    for i in range(0, total, 100):
        batch = events[i:i + 100]
        payload = [{"id": e["id"], "type": e["type"],
                     "timestamp": _iso(e["timestamp"]),
                     "duration_ms": int(e["duration_ms"]),
                     "metadata": json.loads(e["metadata"])}
                    for e in batch]
        _request("POST", f"/sessions/{remote_id}/events", api_url, token,
                 {"events": payload})
        done = min(i + 100, total)
        print(f"\r  Uploading: {done}/{total} events", end="", flush=True)
    print()

    # Complete
    _request("PUT", f"/personal/sessions/{remote_id}/complete", api_url, token)
    store.mark_synced(session_id, remote_id)
    print(f"Pushed: {session_id[:8]} -> {api_url}")


def _iso(ts: float) -> str:
    from datetime import datetime, UTC
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()
