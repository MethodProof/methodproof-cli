#!/bin/sh
# MethodProof hook for Gemini CLI — captures prompts, tools, model calls, sessions.
# Receives JSON on stdin. Posts to local bridge. Fails silently.
# Must complete in <1s to avoid blocking Gemini.

# Skip if no session is running (no pidfile = no daemon = no bridge)
[ -f "${HOME}/.methodproof/methodproof.pid" ] || exit 0

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
    BeforeAgent)
      TYPE="user_prompt"
      META=$(echo "$INPUT" | jq -c '{
        tool: "gemini",
        prompt_preview: (.prompt // "" | .[0:200]),
        prompt_length: (.prompt // "" | length)
      }' 2>/dev/null || echo '{"tool":"gemini"}')
      ;;
    AfterAgent)
      TYPE="agent_completion"
      META=$(echo "$INPUT" | jq -c '{
        tool: "gemini",
        prompt_preview: (.prompt // "" | .[0:200]),
        response_preview: (.prompt_response // "" | .[0:200]),
        response_length: (.prompt_response // "" | length)
      }' 2>/dev/null || echo '{"tool":"gemini"}')
      ;;
    BeforeTool)
      TYPE="tool_call"
      META=$(echo "$INPUT" | jq -c '{
        tool: "gemini",
        tool_name: (.tool_name // "unknown"),
        tool_input_preview: (.tool_input // {} | tostring | .[0:200])
      }' 2>/dev/null || echo '{"tool":"gemini"}')
      ;;
    AfterTool)
      TYPE="tool_result"
      META=$(echo "$INPUT" | jq -c '{
        tool: "gemini",
        tool_name: (.tool_name // "unknown"),
        tool_input_preview: (.tool_input // {} | tostring | .[0:200]),
        result_preview: (.tool_response // {} | tostring | .[0:200])
      }' 2>/dev/null || echo '{"tool":"gemini"}')
      ;;
    BeforeModel)
      TYPE="llm_prompt"
      META=$(echo "$INPUT" | jq -c '{
        tool: "gemini",
        model: "gemini"
      }' 2>/dev/null || echo '{"tool":"gemini","model":"gemini"}')
      ;;
    AfterModel)
      TYPE="llm_completion"
      META=$(echo "$INPUT" | jq -c '{
        tool: "gemini",
        model: "gemini"
      }' 2>/dev/null || echo '{"tool":"gemini","model":"gemini"}')
      ;;
    SessionStart)
      TYPE="gemini_session_start"
      META=$(echo "$INPUT" | jq -c '{
        tool: "gemini",
        gemini_session_id: (.session_id // ""),
        cwd: (.cwd // ""),
        source: (.source // "")
      }' 2>/dev/null || echo '{"tool":"gemini"}')
      ;;
    SessionEnd)
      TYPE="gemini_session_end"
      META=$(echo "$INPUT" | jq -c '{
        tool: "gemini",
        gemini_session_id: (.session_id // ""),
        reason: (.reason // "")
      }' 2>/dev/null || echo '{"tool":"gemini"}')
      ;;
    PreCompress)
      TYPE="context_compact_start"
      META='{"tool":"gemini"}'
      ;;
    Notification)
      TYPE="gemini_event"
      META=$(echo "$INPUT" | jq -c '{
        tool: "gemini",
        event: "notification",
        notification_type: (.notification_type // ""),
        message: (.message // "" | .[0:200])
      }' 2>/dev/null || echo '{"tool":"gemini","event":"notification"}')
      ;;
    *)
      TYPE="gemini_event"
      META="{\"tool\":\"gemini\",\"event\":\"$EVENT\"}"
      ;;
  esac
else
  TYPE="gemini_event"
  META="{\"tool\":\"gemini\",\"event\":\"$EVENT\"}"
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
