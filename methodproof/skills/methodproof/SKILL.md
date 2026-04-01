---
name: methodproof
description: "Query your engineering process data -- sessions, events, graphs, scores, and behavioral moments"
requires:
  bins:
    - curl
    - methodproof
---

# MethodProof -- Process Intelligence

Query your coding sessions to understand how you work. MethodProof captures every
action (LLM prompts, file edits, searches, terminal commands, agent tool calls)
into a process graph.

## List sessions

```bash
methodproof log
```

Shows all local sessions with creation time, duration, event count, and sync status.

## Session summary

```bash
curl -s http://localhost:9877/api/sessions/{SESSION_ID}/stats
```

Returns JSON with event count, duration, and breakdown by event type.

## Process graph

```bash
curl -s http://localhost:9877/api/sessions/{SESSION_ID}/graph
```

Returns JSON with `nodes` (actions) and `edges` (NEXT, RECEIVED, INFORMED, LED_TO,
DISPATCHED, RETURNED, PASTED_FROM, SENT_TO, CONSUMED, PRODUCED, MODIFIED).

## Open visualization

```bash
methodproof view {SESSION_ID}
```

Opens the interactive D3 force-directed graph in the browser.

## Scores (platform mode)

Requires `METHODPROOF_TOKEN` and `METHODPROOF_API_URL` environment variables.

```bash
curl -s -H "Authorization: Bearer $METHODPROOF_TOKEN" \
  "$METHODPROOF_API_URL/sessions/{SESSION_ID}/scores"
```

Returns overall_score, process_score, artifact_score, calibration, and per-signal
scores with weights and evidence.

## Behavioral moments (platform mode)

```bash
curl -s -H "Authorization: Bearer $METHODPROOF_TOKEN" \
  "$METHODPROOF_API_URL/sessions/{SESSION_ID}/moments"
```

Returns detected behavioral patterns: breakthroughs, dead_end_recovery, long_pause,
rapid_iteration, model_switch, agent_loop_spiral, agent_delegation, and more.

## Tips

- Run `methodproof log` first to find the session ID you want to query.
- The bridge server must be running (`methodproof start`) for localhost curl commands.
- Platform API endpoints require authentication env vars.
- Use `methodproof view` for visual exploration, curl for data extraction.
