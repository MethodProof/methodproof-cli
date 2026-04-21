#!/usr/bin/env bash
# MethodProof hook for Claude Code — captures tool calls, prompts, agents.
# Receives JSON on stdin. Posts to local bridge. Fails silently.
# Must complete in <1s to avoid blocking Claude Code.

# Skip if no session is running (no pidfile = no daemon = no bridge)
[ -f "${HOME}/.methodproof/methodproof.pid" ] || exit 0

INPUT=$(cat)

# Model cache: per-Claude-session model attribution.
# The transcript JSONL is the only place Claude Code surfaces the active
# model. Re-reading it on every PreToolUse is too expensive, so we refresh
# a cache at the cheap once-per-turn waypoints (SessionStart / Stop — and
# UserPromptSubmit which delegates to the Python hook that updates it too)
# and read it via a cheap jq lookup on tool events.
_MP_MODEL_CACHE="${HOME}/.methodproof/hook_state/models.json"

# Read the current model for a session. Fast path — no Python subprocess.
_mp_read_model() {
  local sess="$1"
  [ -z "$sess" ] || [ ! -f "$_MP_MODEL_CACHE" ] && return
  command -v jq >/dev/null 2>&1 || return
  jq -r --arg s "$sess" '.[$s].model // empty' "$_MP_MODEL_CACHE" 2>/dev/null
}

# Refresh the cache by shelling out to the Python module (handles JSON
# safely + atomic write). Rare — called on SessionStart / Stop only.
_mp_update_model() {
  local sess="$1" transcript="$2"
  [ -z "$sess" ] || [ -z "$transcript" ] && return
  command -v python3 >/dev/null 2>&1 || return
  python3 -m methodproof.hooks.model_cache update "$sess" "$transcript" \
    >/dev/null 2>&1 || true
}

_mp_clear_model() {
  local sess="$1"
  [ -z "$sess" ] && return
  command -v python3 >/dev/null 2>&1 || return
  python3 -m methodproof.hooks.model_cache clear "$sess" >/dev/null 2>&1 || true
}

if command -v jq >/dev/null 2>&1; then
  EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // "unknown"' 2>/dev/null || echo "unknown")
else
  # Fallback: extract event name with grep (works without jq)
  EVENT=$(echo "$INPUT" | grep -o '"hook_event_name":"[^"]*"' | head -1 | cut -d'"' -f4)
  EVENT=${EVENT:-unknown}
fi

# Timestamp: nanosecond precision where available, second precision fallback
if date +%s.%N >/dev/null 2>&1 && [ "$(date +%N)" != "%N" ]; then
  TS=$(date +%s.%N)
else
  TS=$(date +%s).000
fi

# Build event JSON — use jq if available, else minimal Python
if command -v jq >/dev/null 2>&1; then
  # Pull session + transcript once — cache ops + model attribution use both.
  SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""' 2>/dev/null)
  TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // ""' 2>/dev/null)

  # Refresh model cache at once-per-turn waypoints. Cheap tool events
  # (PreToolUse / PostToolUse) read the cache without touching the
  # transcript.
  case "$EVENT" in
    SessionStart|Stop)
      _mp_update_model "$SESSION_ID" "$TRANSCRIPT"
      ;;
    SessionEnd)
      _mp_clear_model "$SESSION_ID"
      ;;
  esac

  MP_MODEL=$(_mp_read_model "$SESSION_ID")

  case "$EVENT" in
    UserPromptSubmit)
      # Delegate to Python for structural analysis (shell can't do regex classification)
      if echo "$INPUT" | python3 -m methodproof.hooks.claude_code 2>/dev/null; then
        exit 0
      fi
      # Fallback: basic metadata only (no structural analysis)
      TYPE="user_prompt"
      META=$(echo "$INPUT" | jq -c '{prompt_preview: (.prompt // "" | .[0:200]), prompt_length: (.prompt // "" | length)}' 2>/dev/null || echo '{}')
      ;;
    PreToolUse)
      TYPE="tool_call"
      META=$(echo "$INPUT" | jq -c --arg model "$MP_MODEL" '{
        tool: (.tool_name // "unknown"),
        tool_use_id: (.tool_use_id // ""),
        model: (if $model == "" then null else $model end),
        tool_input: (.tool_input // {}),
        tool_input_preview: (
          (.tool_input // {}) as $ti |
          (.tool_name // "unknown") as $tn |
          (if $tn == "Bash" then ($ti.command // "")
           elif $tn == "Read" then ($ti.file_path // "")
           elif $tn == "Write" then ($ti.file_path // "")
           elif $tn == "Edit" then ($ti.file_path // "")
           elif $tn == "Grep" then (($ti.pattern // "") + " " + ($ti.path // ""))
           elif $tn == "Glob" then ($ti.pattern // "")
           elif $tn == "Agent" then ($ti.description // $ti.prompt // "" | .[0:200])
           else ($ti.command // $ti.file_path // $ti.path // $ti.query // $ti.pattern // $ti.url // $ti.description // $ti.prompt // ($ti | tostring)) end
          ) | tostring | .[0:200]
        )
      }' 2>/dev/null || echo '{}')
      ;;
    PostToolUse)
      TYPE="tool_result"
      META=$(echo "$INPUT" | jq -c --arg model "$MP_MODEL" '{
        tool: (.tool_name // "unknown"),
        tool_use_id: (.tool_use_id // ""),
        success: true,
        model: (if $model == "" then null else $model end),
        tool_input: (.tool_input // {}),
        tool_response: (.tool_response // {}),
        tool_input_preview: (
          (.tool_input // {}) as $ti |
          (.tool_name // "unknown") as $tn |
          (if $tn == "Bash" then ($ti.command // "")
           elif $tn == "Read" then ($ti.file_path // "")
           elif $tn == "Write" then ($ti.file_path // "")
           elif $tn == "Edit" then ($ti.file_path // "")
           elif $tn == "Grep" then (($ti.pattern // "") + " " + ($ti.path // ""))
           elif $tn == "Glob" then ($ti.pattern // "")
           elif $tn == "Agent" then ($ti.description // $ti.prompt // "" | .[0:200])
           else ($ti.command // $ti.file_path // $ti.path // $ti.query // $ti.pattern // $ti.url // $ti.description // $ti.prompt // ($ti | tostring)) end
          ) | tostring | .[0:200]
        ),
        result_preview: (
          (.tool_response // {}) as $tr |
          (.tool_name // "unknown") as $tn |
          (if $tn == "Bash" then
             (if ($tr.stderr // "") != "" then ("stderr: " + $tr.stderr) else ($tr.stdout // "") end | .[0:200])
           elif $tn == "Read" then
             (($tr.file.numLines // $tr.numLines // 0) | tostring) + " lines"
           elif $tn == "Grep" then
             (($tr.numFiles // 0) | tostring) + " files, " + (($tr.numLines // 0) | tostring) + " lines"
           elif $tn == "Glob" then
             (($tr.numFiles // 0) | tostring) + " files"
           elif ($tr | type) == "string" then ($tr | .[0:200])
           else ($tr | tostring | .[0:200]) end
          )
        )
      }' 2>/dev/null || echo '{}')
      ;;
    SubagentStart)
      TYPE="agent_launch"
      META=$(echo "$INPUT" | jq -c '{agent_type: (.agent_type // "unknown"), agent_id: (.agent_id // "")}' 2>/dev/null || echo '{}')
      ;;
    SubagentStop)
      TYPE="agent_complete"
      META=$(echo "$INPUT" | jq -c '{agent_type: (.agent_type // "unknown"), agent_id: (.agent_id // ""), last_message_preview: (.last_assistant_message // "" | .[0:200])}' 2>/dev/null || echo '{}')
      ;;
    TaskCreated)
      TYPE="task_created"
      META=$(echo "$INPUT" | jq -c '{task_id: (.task_id // ""), subject: (.task_subject // "")}' 2>/dev/null || echo '{}')
      ;;
    TaskCompleted)
      TYPE="task_completed"
      META=$(echo "$INPUT" | jq -c '{task_id: (.task_id // "")}' 2>/dev/null || echo '{}')
      ;;
    SessionStart)
      TYPE="claude_session_start"
      META=$(echo "$INPUT" | jq -c --arg model "$MP_MODEL" '{
        claude_session_id: (.session_id // ""),
        cwd: (.cwd // ""),
        model: (if $model == "" then null else $model end)
      }' 2>/dev/null || echo '{}')
      ;;
    PostToolUseFailure)
      TYPE="tool_failure"
      META=$(echo "$INPUT" | jq -c '{tool: (.tool_name // "unknown"), is_interrupt: (.is_interrupt // false), success: false, error: (.error // "" | .[0:200])}' 2>/dev/null || echo '{}')
      ;;
    SessionEnd)
      TYPE="claude_session_end"
      META=$(echo "$INPUT" | jq -c '{claude_session_id: (.session_id // "")}' 2>/dev/null || echo '{}')
      ;;
    Stop)
      TYPE="agent_turn_end"
      if [ -n "$MP_MODEL" ]; then
        META="{\"tool\":\"claude_code\",\"model\":\"$MP_MODEL\"}"
      else
        META='{"tool":"claude_code"}'
      fi
      # Extract recap from transcript if available (journal mode)
      TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
      if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
        RECAP=$(grep -E '※ recap:|^recap:' "$TRANSCRIPT" | tail -1 | sed 's/^.*※ recap: *//;s/^recap: *//' | head -c 2000)
        if [ -n "$RECAP" ]; then
          RECAP_ESCAPED=$(echo "$RECAP" | jq -Rs '.' 2>/dev/null || echo '""')
          RECAP_EVENT=",{\"type\":\"context_recap\",\"timestamp\":$TS,\"metadata\":{\"tool\":\"claude_code\",\"recap\":$RECAP_ESCAPED}}"
        fi
      fi
      ;;
    StopFailure)
      TYPE="agent_turn_error"
      META=$(echo "$INPUT" | jq -c '{error: (.error // "" | .[0:200])}' 2>/dev/null || echo '{}')
      ;;
    CwdChanged)
      TYPE="cwd_changed"
      META=$(echo "$INPUT" | jq -c '{cwd: (.cwd // ""), source: "ambiguous"}' 2>/dev/null || echo '{}')
      ;;
    PreCompact)
      TYPE="context_compact_start"
      META='{"tool":"claude_code"}'
      ;;
    PostCompact)
      TYPE="context_compact_end"
      META='{"tool":"claude_code"}'
      ;;
    PermissionRequest)
      TYPE="permission_request"
      META=$(echo "$INPUT" | jq -c '{tool_name: (.tool_name // "unknown")}' 2>/dev/null || echo '{}')
      ;;
    PermissionDenied)
      TYPE="permission_denied"
      META=$(echo "$INPUT" | jq -c '{tool_name: (.tool_name // "unknown")}' 2>/dev/null || echo '{}')
      ;;
    WorktreeCreate)
      TYPE="worktree_create"
      META=$(echo "$INPUT" | jq -c '{worktree_path: (.worktree_path // "")}' 2>/dev/null || echo '{}')
      ;;
    WorktreeRemove)
      TYPE="worktree_remove"
      META=$(echo "$INPUT" | jq -c '{worktree_path: (.worktree_path // "")}' 2>/dev/null || echo '{}')
      ;;
    Elicitation|ElicitationResult)
      TYPE=$(echo "$EVENT" | sed 's/Elicitation$/mcp_elicitation/;s/ElicitationResult/mcp_elicitation_result/')
      META='{"tool":"claude_code"}'
      ;;
    Notification)
      TYPE="notification"
      META=$(echo "$INPUT" | jq -c '{tool: "claude_code", title: (.title // ""), message: ((.message // .text // "")[:1000]), notification_type: (.type // .notification_type // "")}' 2>/dev/null || echo '{"tool":"claude_code"}')
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
PAYLOAD="{\"events\":[{\"type\":\"$TYPE\",\"timestamp\":$TS,\"metadata\":$META}${RECAP_EVENT:-}]}"
RESPONSE=$(curl -s -w "\n%{http_code}" --max-time 1 --connect-timeout 0.5 \
  -X POST http://localhost:9877/events \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null) || true
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
if [ -n "$HTTP_CODE" ] && [ "$HTTP_CODE" != "200" ]; then
  echo "{\"ts\":$TS,\"level\":\"warning\",\"event\":\"hook.post_failed\",\"http_code\":\"$HTTP_CODE\",\"type\":\"$TYPE\",\"payload\":$PAYLOAD}" \
    >> "${HOME}/.methodproof/hook_errors.log" 2>/dev/null || true
fi
