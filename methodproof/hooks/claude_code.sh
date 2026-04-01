#!/usr/bin/env bash
# MethodProof hook for Claude Code — captures tool calls, prompts, agents
# Receives JSON on stdin from Claude Code hook system, posts to local bridge.
# Fails silently if bridge is not running.

set -euo pipefail

INPUT=$(cat)
EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // "unknown"')
SESSION=$(echo "$INPUT" | jq -r '.session_id // ""')
TS=$(date +%s.%N 2>/dev/null || echo "$(date +%s).0")

case "$EVENT" in
  UserPromptSubmit)
    TYPE="user_prompt"
    META=$(echo "$INPUT" | jq -c '{
      prompt_preview: (.prompt // "" | .[0:200]),
      prompt_length: (.prompt // "" | length)
    }')
    ;;
  PreToolUse)
    TYPE="tool_call"
    META=$(echo "$INPUT" | jq -c '{
      tool: (.tool_name // "unknown"),
      tool_use_id: (.tool_use_id // ""),
      args_preview: ((.tool_input // {}) | tostring | .[0:300])
    }')
    ;;
  PostToolUse)
    TYPE="tool_result"
    META=$(echo "$INPUT" | jq -c '{
      tool: (.tool_name // "unknown"),
      tool_use_id: (.tool_use_id // ""),
      success: ((.tool_response // {}).success // true)
    }')
    ;;
  SubagentStart)
    TYPE="agent_launch"
    META=$(echo "$INPUT" | jq -c '{
      agent_type: (.agent_type // "unknown"),
      agent_id: (.agent_id // "")
    }')
    ;;
  SubagentStop)
    TYPE="agent_complete"
    META=$(echo "$INPUT" | jq -c '{
      agent_type: (.agent_type // "unknown"),
      agent_id: (.agent_id // "")
    }')
    ;;
  TaskCreated)
    TYPE="task_created"
    META=$(echo "$INPUT" | jq -c '{
      task_id: (.task_id // ""),
      subject: (.subject // "")
    }')
    ;;
  TaskCompleted)
    TYPE="task_completed"
    META=$(echo "$INPUT" | jq -c '{task_id: (.task_id // "")}')
    ;;
  SessionStart)
    TYPE="claude_session_start"
    META=$(echo "$INPUT" | jq -c '{
      claude_session_id: (.session_id // ""),
      cwd: (.cwd // "")
    }')
    ;;
  *)
    TYPE="claude_code_event"
    META=$(echo "$INPUT" | jq -c '{event: (.hook_event_name // "unknown")}')
    ;;
esac

curl -s -X POST http://localhost:9877/events \
  -H "Content-Type: application/json" \
  -d "{\"events\":[{\"type\":\"$TYPE\",\"timestamp\":$TS,\"metadata\":$META}]}" \
  >/dev/null 2>&1 || true
