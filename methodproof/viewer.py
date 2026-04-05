"""Local session viewer — terminal audit of captured data."""

import json
from typing import Any

from methodproof import config, store

SENSITIVE_FIELDS = {"prompt_text", "response_text", "command", "output_snippet", "diff", "query"}


def view(session: dict[str, Any]) -> None:
    sid = session["id"]
    events = store.get_events(sid)
    cfg = config.load()
    capture = cfg.get("capture", {})
    active = [k for k, v in capture.items() if v]

    # Header
    dur = _duration(session)
    vis = session.get("visibility", "private")
    tags = json.loads(session.get("tags") or "[]")
    repo = session.get("repo_url") or "none"
    synced = "yes" if session.get("synced") else "no"

    print(f"\nSession {sid[:8]}  ·  {len(events)} events  ·  {dur}  ·  {vis}  ·  synced: {synced}")
    if tags:
        print(f"Tags: {', '.join(tags)}")
    print(f"Repo: {repo}")
    print(f"Consent: {', '.join(active)}")

    if not events:
        print("\nNo events captured.")
        return

    # Group by type
    by_type: dict[str, list[dict]] = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)

    start_ts = events[0]["timestamp"]

    # Per-type receipt: show every event with its captured fields
    print(f"\n{'─' * 70}")
    for etype, items in sorted(by_type.items(), key=lambda x: -len(x[1])):
        first = _offset(items[0]["timestamp"], start_ts)
        last = _offset(items[-1]["timestamp"], start_ts)
        print(f"\n  {etype}  ({len(items)} events, {first} – {last})")

        # Collect all metadata keys across events of this type
        type_fields: set[str] = set()
        for e in items:
            meta = json.loads(e.get("metadata") or "{}")
            type_fields.update(meta.keys())

        safe = sorted(type_fields - SENSITIVE_FIELDS)
        sensitive = sorted(type_fields & SENSITIVE_FIELDS)
        if safe:
            print(f"  fields: {', '.join(safe)}")
        if sensitive:
            print(f"  sensitive (encrypted): {', '.join(sensitive)}")

        # Individual event lines
        for e in items:
            ts = _offset(e["timestamp"], start_ts)
            meta = json.loads(e.get("metadata") or "{}")
            summary = _event_summary(etype, meta)
            print(f"    {ts}  {summary}")

    # Footer
    print(f"\n{'─' * 70}")
    print(f"Total: {len(events)} events across {len(by_type)} types.")
    print("Run `methodproof push` to upload.")
    print("Full graph + analysis at app.methodproof.com after push.\n")


def _event_summary(etype: str, meta: dict[str, Any]) -> str:
    """One-line summary per event — structural info only, no sensitive content."""
    if etype in ("file_edit", "file_create", "file_delete"):
        path = meta.get("path", "?")
        lang = meta.get("language", "")
        lines = meta.get("line_count", "")
        parts = [path]
        if lang:
            parts.append(lang)
        if lines:
            parts.append(f"{lines} lines")
        return " · ".join(parts)
    if etype == "git_commit":
        msg = meta.get("message", "")[:60]
        files = meta.get("files_changed", "?")
        return f"{msg}  ({files} files)"
    if etype in ("llm_prompt", "llm_completion", "agent_prompt", "agent_completion"):
        model = meta.get("model", "?")
        tokens = meta.get("token_count", meta.get("tokens", ""))
        parts = [model]
        if tokens:
            parts.append(f"{tokens} tokens")
        return " · ".join(parts)
    if etype in ("terminal_cmd", "test_run"):
        cmd = meta.get("command", meta.get("cmd", ""))
        if cmd:
            return _truncate(cmd, 60)
        exit_code = meta.get("exit_code", "")
        return f"exit {exit_code}" if exit_code != "" else ""
    if etype in ("web_visit", "browser_visit"):
        return meta.get("domain", meta.get("url", "?"))
    if etype in ("web_search", "browser_search"):
        length = meta.get("query_length", meta.get("word_count", ""))
        return f"query ({length} chars)" if length else "query"
    if etype == "browser_copy":
        length = meta.get("text_length", "?")
        return f"{length} chars"
    if etype == "browser_tab_switch":
        return meta.get("domain", "")
    if etype == "browser_ai_chat":
        return meta.get("platform", "?")
    if etype in ("inline_completion_shown", "inline_completion_accepted", "inline_completion_rejected"):
        path = meta.get("path", "?")
        lang = meta.get("language", "")
        return f"{path} · {lang}" if lang else path
    # Fallback: show non-sensitive key=value pairs
    safe = {k: v for k, v in meta.items() if k not in SENSITIVE_FIELDS}
    if safe:
        return ", ".join(f"{k}={_truncate(str(v), 30)}" for k, v in list(safe.items())[:4])
    return ""


def _duration(s: dict[str, Any]) -> str:
    if not s.get("completed_at") or not s.get("created_at"):
        return "active"
    secs = int(s["completed_at"] - s["created_at"])
    return f"{secs // 60}:{secs % 60:02d}"


def _offset(ts: float, start: float) -> str:
    secs = max(0, int(ts - start))
    return f"{secs // 60}:{secs % 60:02d}"


def _truncate(s: str, n: int) -> str:
    return s[:n] + "…" if len(s) > n else s
