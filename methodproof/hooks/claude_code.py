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
    from methodproof.analysis import analyze_prompt
except ImportError:
    analyze_prompt = lambda _: {}

_TYPE_MAP = {
    "UserPromptSubmit": "user_prompt",
    "PreToolUse": "tool_call",
    "PostToolUse": "tool_result",
    "SubagentStart": "agent_launch",
    "SubagentStop": "agent_complete",
    "TaskCreated": "task_created",
    "TaskCompleted": "task_completed",
    "SessionStart": "claude_session_start",
}

_META_EXTRACTORS = {
    "UserPromptSubmit": lambda d: {
        "prompt_preview": (d.get("prompt") or "")[:200],
        "prompt_length": len(d.get("prompt") or ""),
        **analyze_prompt(d.get("prompt") or ""),
    },
    "PreToolUse": lambda d: {"tool": d.get("tool_name", "unknown"), "tool_use_id": d.get("tool_use_id", "")},
    "PostToolUse": lambda d: {"tool": d.get("tool_name", "unknown"), "tool_use_id": d.get("tool_use_id", "")},
    "SubagentStart": lambda d: {"agent_type": d.get("agent_type", "unknown"), "agent_id": d.get("agent_id", "")},
    "SubagentStop": lambda d: {"agent_type": d.get("agent_type", "unknown"), "agent_id": d.get("agent_id", "")},
    "TaskCreated": lambda d: {"task_id": d.get("task_id", ""), "subject": d.get("subject", "")},
    "TaskCompleted": lambda d: {"task_id": d.get("task_id", "")},
    "SessionStart": lambda d: {"claude_session_id": d.get("session_id", ""), "cwd": d.get("cwd", "")},
}


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    event = data.get("hook_event_name", "unknown")
    etype = _TYPE_MAP.get(event, "claude_code_event")
    extractor = _META_EXTRACTORS.get(event)
    meta = extractor(data) if extractor else {"event": event}
    ts = time.time()

    payload = json.dumps({"events": [{"type": etype, "timestamp": ts, "metadata": meta}]}).encode()
    req = urllib.request.Request(
        "http://localhost:9877/events", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass


if __name__ == "__main__":
    main()
