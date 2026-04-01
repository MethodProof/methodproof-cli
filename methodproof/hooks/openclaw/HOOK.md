---
name: methodproof
description: "Captures process telemetry for MethodProof engineering intelligence"
metadata: { "openclaw": { "emoji": "M", "events": ["command:new", "command:reset", "command:stop", "message:received", "message:sent"] } }
---

# MethodProof Telemetry Hook

Captures OpenClaw agent interactions (messages, commands) and pushes events to the
MethodProof bridge for process graph construction.

Requires the MethodProof bridge running on localhost:9877 (`methodproof start`).

Set `METHODPROOF_MODE=assessment` with `METHODPROOF_API_URL` and `METHODPROOF_TOKEN`
to push events to the platform API instead.
