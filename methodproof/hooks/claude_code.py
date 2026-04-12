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

def _extract_result_text(response) -> str:
    """Extract plain text from tool_response regardless of shape.

    Claude Code sends:
    - str  — Bash, Write, Edit, simple tools
    - list — Read, Grep, Glob: [{"type": "text", "text": "..."}]
    - dict — rare structured responses
    """
    if isinstance(response, str):
        return response[:500]
    if isinstance(response, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in response
            if not isinstance(block, dict) or block.get("type") == "text"
        ]
        return "\n".join(parts)[:500]
    if isinstance(response, dict):
        return response.get("text") or response.get("content") or json.dumps(response)[:500]
    return str(response)[:500]


def _build_prompt_meta(text: str) -> dict:
    sa = analyze_prompt(text)
    sa["prompt_length"] = len(text)
    sa["prompt_summary"] = compose_summary(sa)
    return sa


_TYPE_MAP = {
    # Human-initiated
    "UserPromptSubmit": "user_prompt",
    # Tool lifecycle
    "PreToolUse": "tool_call",
    "PostToolUse": "tool_result",
    "PostToolUseFailure": "tool_failure",
    # Agent lifecycle
    "SubagentStart": "agent_launch",
    "SubagentStop": "agent_complete",
    # Task lifecycle
    "TaskCreated": "task_start",
    "TaskCompleted": "task_end",
    # Session lifecycle
    "SessionStart": "claude_session_start",
    "SessionEnd": "claude_session_end",
    "Stop": "agent_turn_end",
    "StopFailure": "agent_turn_error",
    # Context
    "CwdChanged": "cwd_changed",
    "PreCompact": "context_compact_start",
    "PostCompact": "context_compact_end",
    # Permissions
    "PermissionRequest": "permission_request",
    "PermissionDenied": "permission_denied",
    # MCP
    "Elicitation": "mcp_elicitation",
    "ElicitationResult": "mcp_elicitation_result",
    # Worktree
    "WorktreeCreate": "worktree_create",
    "WorktreeRemove": "worktree_remove",
}

_TOOL = "claude_code"

def _tool_input_preview(d: dict) -> str:
    """Compact one-line summary of tool input for journal mode."""
    inp = d.get("tool_input") or {}
    # Flatten the most useful field per tool rather than dumping the whole dict
    for key in ("command", "file_path", "path", "query", "url", "description"):
        if key in inp:
            return str(inp[key])[:300]
    return json.dumps(inp)[:300] if inp else ""


_META_EXTRACTORS = {
    "UserPromptSubmit": lambda d: {
        "tool": _TOOL,
        "prompt_text": d.get("prompt") or "",
        "prompt_preview": _build_prompt_meta(d.get("prompt") or "").get("prompt_summary", ""),
        "prompt_length": len(d.get("prompt") or ""),
    },
    "PreToolUse": lambda d: {
        "tool": _TOOL, "tool_name": d.get("tool_name", "unknown"),
        "tool_input": d.get("tool_input") or {},
        "tool_input_preview": _tool_input_preview(d),
    },
    "PostToolUse": lambda d: {
        "tool": _TOOL, "tool_name": d.get("tool_name", "unknown"), "success": True,
        "tool_input": d.get("tool_input") or {},
        "tool_response": d.get("tool_response") or {},
        "tool_input_preview": _tool_input_preview(d),
        "result_preview": _extract_result_text(d.get("tool_response")),
    },
    "PostToolUseFailure": lambda d: {
        "tool": _TOOL, "tool_name": d.get("tool_name", "unknown"),
        "success": False, "is_interrupt": d.get("is_interrupt", False),
        "tool_input": d.get("tool_input") or {},
        "error": str(d.get("error", ""))[:200],
    },
    "SubagentStart": lambda d: {"tool": _TOOL, "agent_type": d.get("agent_type", "unknown"), "agent_id": d.get("agent_id", "")},
    "SubagentStop": lambda d: {
        "tool": _TOOL, "agent_type": d.get("agent_type", "unknown"), "agent_id": d.get("agent_id", ""),
        "last_assistant_message": d.get("last_assistant_message", ""),
        "last_message_preview": str(d.get("last_assistant_message", ""))[:200],
    },
    "TaskCreated": lambda d: {"tool": _TOOL, "task_id": d.get("task_id", ""), "subject": d.get("task_subject", "")},
    "TaskCompleted": lambda d: {"tool": _TOOL, "task_id": d.get("task_id", "")},
    "SessionStart": lambda d: {"tool": _TOOL, "session_id": d.get("session_id", ""), "cwd": d.get("cwd", "")},
    "SessionEnd": lambda d: {"tool": _TOOL, "session_id": d.get("session_id", "")},
    "Stop": lambda d: {"tool": _TOOL},
    "StopFailure": lambda d: {"tool": _TOOL, "error": str(d.get("error", ""))[:200]},
    "CwdChanged": lambda d: {
        "tool": _TOOL, "cwd": d.get("cwd", ""),
        # NOTE: fires for both human `cd` and Claude tool use — caller is ambiguous
        "source": "ambiguous",
    },
    "PreCompact": lambda d: {"tool": _TOOL},
    "PostCompact": lambda d: {"tool": _TOOL},
    "PermissionRequest": lambda d: {"tool": _TOOL, "tool_name": d.get("tool_name", "unknown")},
    "PermissionDenied": lambda d: {"tool": _TOOL, "tool_name": d.get("tool_name", "unknown")},
    "Elicitation": lambda d: {"tool": _TOOL},
    "ElicitationResult": lambda d: {"tool": _TOOL},
    "WorktreeCreate": lambda d: {"tool": _TOOL, "worktree_path": d.get("worktree_path", "")},
    "WorktreeRemove": lambda d: {"tool": _TOOL, "worktree_path": d.get("worktree_path", "")},
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
