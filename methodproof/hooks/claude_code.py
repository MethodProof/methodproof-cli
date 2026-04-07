#!/usr/bin/env python3
"""MethodProof hook for Claude Code — cross-platform Python equivalent of claude_code.sh.

Receives JSON on stdin. Posts to local bridge. Fails silently.
Uses only stdlib — no jq, no curl dependency.
"""

import json
import sys
import time
import urllib.request

try:
    from methodproof.analysis import analyze_prompt, compose_summary
except ImportError:
    analyze_prompt = lambda _: {}
    compose_summary = lambda _: ""

def _build_prompt_meta(text: str) -> dict:
    sa = analyze_prompt(text)
    sa["prompt_length"] = len(text)
    sa["prompt_summary"] = compose_summary(sa)
    return sa


_TYPE_MAP = {
    "UserPromptSubmit": "user_prompt",
    "PreToolUse": "tool_call",
    "PostToolUse": "tool_result",
    "SubagentStart": "agent_launch",
    "SubagentStop": "agent_complete",
    "TaskCreated": "task_start",
    "TaskCompleted": "task_end",
    "SessionStart": "claude_session_start",
}

_TOOL = "claude_code"

_META_EXTRACTORS = {
    "UserPromptSubmit": lambda d: {
        "tool": _TOOL, "prompt_preview": _build_prompt_meta(d.get("prompt") or "").get("prompt_summary", ""),
        "prompt_length": len(d.get("prompt") or ""),
    },
    "PreToolUse": lambda d: {"tool": _TOOL, "tool_name": d.get("tool_name", "unknown")},
    "PostToolUse": lambda d: {"tool": _TOOL, "tool_name": d.get("tool_name", "unknown"), "success": True},
    "SubagentStart": lambda d: {"tool": _TOOL, "agent_type": d.get("agent_type", "unknown"), "agent_id": d.get("agent_id", "")},
    "SubagentStop": lambda d: {"tool": _TOOL, "agent_type": d.get("agent_type", "unknown"), "agent_id": d.get("agent_id", "")},
    "TaskCreated": lambda d: {"tool": _TOOL, "task_id": d.get("task_id", ""), "subject": d.get("task_subject", "")},
    "TaskCompleted": lambda d: {"tool": _TOOL, "task_id": d.get("task_id", "")},
    "SessionStart": lambda d: {"tool": _TOOL, "session_id": d.get("session_id", ""), "cwd": d.get("cwd", "")},
}


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    event = data.get("hook_event_name", "unknown")
    etype = _TYPE_MAP.get(event)
    if not etype:
        return  # Unmapped hook event — drop rather than send invalid type
    extractor = _META_EXTRACTORS.get(event)
    meta = extractor(data) if extractor else {"tool": _TOOL}
    ts = time.time()

    payload = json.dumps({"events": [{"type": etype, "timestamp": ts, "metadata": meta}]}).encode()
    req = urllib.request.Request(
        "http://localhost:9877/events", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=1)
    except Exception as exc:
        import pathlib
        log = pathlib.Path.home() / ".methodproof" / "hook_errors.log"
        try:
            with open(log, "a") as f:
                f.write(f"{time.time():.0f} hook.post_failed type={etype} error={exc}\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
