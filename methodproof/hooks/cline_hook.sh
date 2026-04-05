#!/bin/sh
# MethodProof hook for Cline — captures tool actions via env vars/args.
# Cline invokes hook scripts with context as environment variables.
# Posts to local bridge. Fails silently.
# Must complete in <1s to avoid blocking Cline.

# Cline sets: CLINE_ACTION, CLINE_TOOL, CLINE_FILE, CLINE_TASK_ID
# Falls back to $1 (action) and $2 (tool name) if env vars absent.
ACTION="${CLINE_ACTION:-${1:-unknown}}"
TOOL_NAME="${CLINE_TOOL:-${2:-unknown}}"

if date +%s.%N >/dev/null 2>&1 && [ "$(date +%N)" != "%N" ]; then
  TS=$(date +%s.%N)
else
  TS=$(date +%s).000
fi

case "$ACTION" in
  pre_tool|before_tool)
    TYPE="tool_call"
    ;;
  post_tool|after_tool)
    TYPE="tool_result"
    ;;
  task_start)
    TYPE="task_start"
    ;;
  task_end)
    TYPE="task_end"
    ;;
  *)
    TYPE="cline_event"
    ;;
esac

META="{\"tool\":\"cline\",\"tool_name\":\"$TOOL_NAME\",\"action\":\"$ACTION\"}"

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
