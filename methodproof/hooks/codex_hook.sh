#!/bin/sh
# MethodProof hook for Codex CLI — captures tool calls, prompts, sessions.
# Receives JSON on stdin. Posts to local bridge. Fails silently.
# Must complete in <1s to avoid blocking Codex.

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
    UserPromptSubmit)
      TYPE="user_prompt"
      META=$(echo "$INPUT" | jq -c '{tool: "codex", prompt_length: (.prompt // "" | length), prompt_preview: (.prompt // "" | .[0:200])}' 2>/dev/null || echo '{"tool":"codex"}')
      ;;
    PreToolUse)
      TYPE="tool_call"
      META=$(echo "$INPUT" | jq -c '{tool: "codex", tool_name: (.tool_name // "unknown")}' 2>/dev/null || echo '{"tool":"codex"}')
      ;;
    PostToolUse)
      TYPE="tool_result"
      META=$(echo "$INPUT" | jq -c '{tool: "codex", tool_name: (.tool_name // "unknown")}' 2>/dev/null || echo '{"tool":"codex"}')
      ;;
    SessionStart)
      TYPE="codex_session_start"
      META=$(echo "$INPUT" | jq -c '{tool: "codex", cwd: (.cwd // "")}' 2>/dev/null || echo '{"tool":"codex"}')
      ;;
    Stop)
      TYPE="codex_session_end"
      META=$(echo "$INPUT" | jq -c '{tool: "codex", reason: (.reason // "")}' 2>/dev/null || echo '{"tool":"codex"}')
      ;;
    *)
      TYPE="codex_event"
      META="{\"tool\":\"codex\",\"event\":\"$EVENT\"}"
      ;;
  esac
else
  TYPE="codex_event"
  META="{\"tool\":\"codex\",\"event\":\"$EVENT\"}"
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
