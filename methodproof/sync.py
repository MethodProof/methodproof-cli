"""Push local sessions to the MethodProof platform."""

import gzip
import json
import urllib.error
import urllib.request
from typing import Any

from methodproof import store


def sync_metadata(session: dict[str, Any], token: str, api_url: str) -> None:
    """Sync repo, tags, and visibility for an already-pushed session."""
    remote_id = session.get("remote_id")
    if not remote_id:
        return
    repo_url = session.get("repo_url")
    if repo_url:
        _request("POST", f"/sessions/{remote_id}/repos", api_url, token,
                 {"remote_url": repo_url, "detected_by": "cli"})
    tags = json.loads(session.get("tags") or "[]")
    if tags:
        _request("PUT", f"/sessions/{remote_id}/tags", api_url, token,
                 {"tags": tags})
    if session.get("visibility") == "public":
        _request("PUT", f"/sessions/{remote_id}/visibility", api_url, token,
                 {"visibility": "public"})


def _raw_request(
    method: str, url: str, token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if body is not None:
        data = gzip.compress(json.dumps(body).encode())
    else:
        data = None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Encoding"] = "gzip"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _refresh_token(api_url: str, refresh: str) -> tuple[str, str] | None:
    """Exchange refresh token for new access + refresh tokens. Returns None on failure."""
    try:
        result = _raw_request("POST", f"{api_url}/auth/refresh", "", {"refresh_token": refresh})
        return result["access_token"], result["refresh_token"]
    except Exception as exc:
        from methodproof.agents.base import log
        log("warning", "sync.refresh_token_failed", error=str(exc))
        return None


def _request(
    method: str, path: str, api_url: str, token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{api_url}{path}"
    try:
        return _raw_request(method, url, token, body)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            from methodproof import config
            cfg = config.load()
            refresh = cfg.get("refresh_token", "")
            if refresh:
                pair = _refresh_token(api_url, refresh)
                if pair:
                    cfg["token"], cfg["refresh_token"] = pair
                    config.save(cfg)
                    return _raw_request(method, url, cfg["token"], body)
            raise SystemExit("Session expired. Run `methodproof login` to re-authenticate.") from None
        detail = ""
        if exc.fp:
            try:
                detail = json.loads(exc.read()).get("detail", "")
            except Exception as parse_err:
                detail = f"(response unreadable: {parse_err})"
        raise SystemExit(f"API error {exc.code}: {detail}") from None


def push(session_id: str, token: str, api_url: str) -> str:
    """Upload a local session to the platform."""
    session = store.get_session(session_id)
    if not session:
        raise SystemExit(f"Session not found: {session_id}")
    if session["synced"]:
        print(f"Already synced: {session_id[:8]}")
        return session.get("remote_id", "")

    # Create remote session (include binding + device_id if available)
    print("Creating remote session...", end=" ", flush=True)
    create_body: dict[str, Any] = {}
    if session.get("session_binding"):
        create_body["session_binding"] = session["session_binding"]
    if session.get("device_id"):
        create_body["device_id"] = session["device_id"]
    result = _request("POST", "/personal/sessions", api_url, token,
                      create_body or None)
    remote_id = result["session_id"]
    print(f"done ({remote_id[:8]})")

    # Upload events in batches (with hash chain if available)
    events = store.get_events(session_id)
    event_hashes = store.get_event_hashes(session_id)
    hash_lookup = {h["event_id"]: h["hash"] for h in event_hashes}
    total = len(events)
    batch_size = 500
    try:
        for i in range(0, total, batch_size):
            batch = events[i:i + batch_size]
            payload = [{"id": e["id"], "type": e["type"],
                         "timestamp": _iso(e["timestamp"]),
                         "timestamp_raw": e["timestamp"],
                         "duration_ms": int(e["duration_ms"]),
                         "metadata": json.loads(e["metadata"]),
                         "hash": hash_lookup.get(e["id"], "")}
                        for e in batch]
            for attempt in range(5):
                try:
                    _request("POST", f"/sessions/{remote_id}/events", api_url, token,
                             {"events": payload})
                    break
                except SystemExit as exc:
                    if "429" in str(exc) and attempt < 4:
                        import time
                        time.sleep(10 * (attempt + 1))
                    else:
                        raise
            done = min(i + batch_size, total)
            print(f"\r  Uploading: {done}/{total} events", end="", flush=True)
        print()
    except SystemExit:
        # Event upload failed — abandon the remote session so it doesn't show as LIVE
        try:
            _request("PUT", f"/personal/sessions/{remote_id}/abandon", api_url, token)
        except Exception:
            pass
        raise

    # Attestation (if signing key available)
    from methodproof.integrity import has_keypair
    if has_keypair() and event_hashes:
        try:
            import hashlib as _hl
            from methodproof.integrity import sign_attestation, compute_binary_hash, get_public_key_pem
            from methodproof import __version__
            root_hash = event_hashes[0]["hash"]
            leaf_hash = event_hashes[-1]["hash"]
            binary_hash = compute_binary_hash()
            signature = sign_attestation(
                session_id, root_hash, leaf_hash, total, __version__, binary_hash,
            )
            pub_pem = get_public_key_pem().decode()
            fp = _hl.sha256(pub_pem.encode()).hexdigest()
            try:
                _request("POST", "/personal/signing-keys", api_url, token,
                         {"public_key_pem": pub_pem, "fingerprint": fp})
            except SystemExit:
                pass  # 409 = already registered
            _request("POST", f"/sessions/{remote_id}/attestation", api_url, token, {
                "session_id": session_id, "root_hash": root_hash, "leaf_hash": leaf_hash,
                "event_count": total, "cli_version": __version__, "binary_hash": binary_hash,
                "signature": signature, "key_fingerprint": fp,
            })
            print(f"  Attestation: signed ({fp[:8]})")
        except ImportError:
            pass  # cryptography not installed

    # Complete
    _request("PUT", f"/personal/sessions/{remote_id}/complete", api_url, token)
    store.mark_synced(session_id, remote_id)

    # Sync metadata (repo, tags, visibility)
    session["remote_id"] = remote_id
    sync_metadata(session, token, api_url)

    print(f"Pushed: {session_id[:8]} -> {api_url}")
    return remote_id


def _iso(ts: float) -> str:
    from datetime import datetime, UTC
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def sync_research_consent(token: str, api_url: str) -> None:
    """Sync research consent between CLI (cache) and platform (source of truth)."""
    from methodproof import config
    from methodproof.agents.base import log

    try:
        cfg = config.load()

        # Push pending local change first
        if cfg.get("_pending_research_sync"):
            _request("PUT", "/research/opt-in", api_url, token, {
                "opt_in": cfg.get("research_consent", False),
                "contribution_level": cfg.get("contribution_level") or "structural",
            })
            cfg["_pending_research_sync"] = False
            config.save(cfg)

        # Pull canonical state from platform
        status = _request("GET", "/research/status", api_url, token)
        cfg = config.load()
        cfg["research_consent"] = status.get("opt_in", False)
        cfg["contribution_level"] = status.get("contribution_level")
        config.save(cfg)
    except (SystemExit, Exception) as exc:
        log("warning", "sync.research_consent_failed", error=str(exc))
