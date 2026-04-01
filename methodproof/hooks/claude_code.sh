#!/usr/bin/env bash
# MethodProof hook for Claude Code — captures tool calls, prompts, agents.
# Receives JSON on stdin. Posts to local bridge. Fails silently.
# Must complete in <1s to avoid blocking Claude Code.

# Require jq — without it, fall back to a minimal Python parser
INPUT=$(cat)

if command -v jq >/dev/null 2>&1; then
  EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // "unknown"' 2>/dev/null || echo "unknown")
else
  # Fallback: extract event name with grep (works without jq)
  EVENT=$(echo "$INPUT" | grep -o '"hook_event_name":"[^"]*"' | head -1 | cut -d'"' -f4)
  EVENT=${EVENT:-unknown}
fi

# Timestamp: millisecond precision on Linux, second precision on macOS
if date +%s.%N >/dev/null 2>&1 && [ "$(date +%N)" != "%N" ]; then
  TS=$(date +%s.%3N)
else
  TS=$(date +%s).000
fi

# Build event JSON — use jq if available, else minimal Python
if command -v jq >/dev/null 2>&1; then
  case "$EVENT" in
    UserPromptSubmit)
      TYPE="user_prompt"
      META=$(echo "$INPUT" | jq -c '{prompt_preview: (.prompt // "" | .[0:200]), prompt_length: (.prompt // "" | length)}' 2>/dev/null || echo '{}')
      ;;
    PreToolUse)
      TYPE="tool_call"
      META=$(echo "$INPUT" | jq -c '{tool: (.tool_name // "unknown"), tool_use_id: (.tool_use_id // "")}' 2>/dev/null || echo '{}')
      ;;
    PostToolUse)
      TYPE="tool_result"
      META=$(echo "$INPUT" | jq -c '{tool: (.tool_name // "unknown"), tool_use_id: (.tool_use_id // "")}' 2>/dev/null || echo '{}')
      ;;
    SubagentStart)
      TYPE="agent_launch"
      META=$(echo "$INPUT" | jq -c '{agent_type: (.agent_type // "unknown"), agent_id: (.agent_id // "")}' 2>/dev/null || echo '{}')
      ;;
    SubagentStop)
      TYPE="agent_complete"
      META=$(echo "$INPUT" | jq -c '{agent_type: (.agent_type // "unknown"), agent_id: (.agent_id // "")}' 2>/dev/null || echo '{}')
      ;;
    TaskCreated)
      TYPE="task_created"
      META=$(echo "$INPUT" | jq -c '{task_id: (.task_id // ""), subject: (.subject // "")}' 2>/dev/null || echo '{}')
      ;;
    TaskCompleted)
      TYPE="task_completed"
      META=$(echo "$INPUT" | jq -c '{task_id: (.task_id // "")}' 2>/dev/null || echo '{}')
      ;;
    SessionStart)
      TYPE="claude_session_start"
      META=$(echo "$INPUT" | jq -c '{claude_session_id: (.session_id // ""), cwd: (.cwd // "")}' 2>/dev/null || echo '{}')
      ;;
    *)
      TYPE="claude_code_event"
      META="{\"event\":\"$EVENT\"}"
      ;;
  esac
else
  # No jq — emit minimal event with just the type
  TYPE="claude_code_event"
  META="{\"event\":\"$EVENT\"}"
fi

# Post to bridge with strict 1-second timeout (never block Claude Code)
curl -s --max-time 1 --connect-timeout 0.5 \
  -X POST http://localhost:9877/events \
  -H "Content-Type: application/json" \
  -d "{\"events\":[{\"type\":\"$TYPE\",\"timestamp\":$TS,\"metadata\":$META}]}" \
  >/dev/null 2>&1 || true
