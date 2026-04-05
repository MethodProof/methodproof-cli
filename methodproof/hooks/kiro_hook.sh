#!/bin/sh
# MethodProof hook for Kiro — captures tool calls, tasks, agents, prompts.
# Receives JSON on stdin. Posts to local bridge. Fails silently.
# Must complete in <1s to avoid blocking Kiro.

INPUT=$(cat)

if command -v jq >/dev/null 2>&1; then
  EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // "unknown"' 2>/dev/null || echo "unknown")
else
  EVENT=$(echo "$INPUT" | grep -o '"hook_event_name":"[^"]*"' | head -1 | cut -d'"' -f4)
  EVENT=${EVENT:-unknown}
fi

if date +%s.%N >/dev/null 2>&1 && [ "$(date +%N)" != "%N" ]; then
  TS=$(date +%s.%N)
else
  TS=$(date +%s).000
fi

if command -v jq >/dev/null 2>&1; then
  case "$EVENT" in
    userPromptSubmit)
      TYPE="user_prompt"
      META=$(echo "$INPUT" | jq -c '{tool: "kiro", prompt_length: (.prompt // "" | length), prompt_preview: (.prompt // "" | .[0:200])}' 2>/dev/null || echo '{"tool":"kiro"}')
      ;;
    preToolUse)
      TYPE="tool_call"
      META=$(echo "$INPUT" | jq -c '{tool: "kiro", tool_name: (.tool_name // "unknown")}' 2>/dev/null || echo '{"tool":"kiro"}')
      ;;
    postToolUse)
      TYPE="tool_result"
      META=$(echo "$INPUT" | jq -c '{tool: "kiro", tool_name: (.tool_name // "unknown")}' 2>/dev/null || echo '{"tool":"kiro"}')
      ;;
    preTaskExecution)
      TYPE="task_start"
      META=$(echo "$INPUT" | jq -c '{tool: "kiro", task_id: (.task_id // "")}' 2>/dev/null || echo '{"tool":"kiro"}')
      ;;
    postTaskExecution)
      TYPE="task_end"
      META=$(echo "$INPUT" | jq -c '{tool: "kiro", task_id: (.task_id // "")}' 2>/dev/null || echo '{"tool":"kiro"}')
      ;;
    agentSpawn)
      TYPE="agent_launch"
      META=$(echo "$INPUT" | jq -c '{tool: "kiro", agent_type: (.agent_type // "unknown"), agent_id: (.agent_id // "")}' 2>/dev/null || echo '{"tool":"kiro"}')
      ;;
    stop)
      TYPE="kiro_session_end"
      META=$(echo "$INPUT" | jq -c '{tool: "kiro", reason: (.reason // "")}' 2>/dev/null || echo '{"tool":"kiro"}')
      ;;
    *)
      TYPE="kiro_event"
      META="{\"tool\":\"kiro\",\"event\":\"$EVENT\"}"
      ;;
  esac
else
  TYPE="kiro_event"
  META="{\"tool\":\"kiro\",\"event\":\"$EVENT\"}"
fi

PAYLOAD="{\"events\":[{\"type\":\"$TYPE\",\"timestamp\":$TS,\"metadata\":$META}]}"
RESPONSE=$(curl -s -w "\n%{http_code}" --max-time 1 --connect-timeout 0.5 \
  -X POST http://localhost:9877/events \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null) || true
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
if [ -n "$HTTP_CODE" ] && [ "$HTTP_CODE" != "200" ]; then
  echo "{\"ts\":$TS,\"level\":\"warning\",\"event\":\"hook.post_failed\",\"http_code\":\"$HTTP_CODE\",\"type\":\"$TYPE\",\"payload\":$PAYLOAD}" \
    >> "${HOME}/.methodproof/hook_errors.log" 2>/dev/null || true
fi
