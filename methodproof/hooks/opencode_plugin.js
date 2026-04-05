// MethodProof plugin for OpenCode — captures tool calls and sessions.
// Posts to local bridge. Fails silently. 1s timeout on all calls.

const BRIDGE = "http://localhost:9877/events";

function post(type, metadata) {
  const body = JSON.stringify({
    events: [{ type, timestamp: Date.now() / 1000, metadata }],
  });
  fetch(BRIDGE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: AbortSignal.timeout(1000),
    body,
  }).catch(() => {});
}

module.exports = function () {
  return {
    beforeTool: async (toolName) => {
      post("tool_call", { tool: "opencode", tool_name: toolName });
    },
    afterTool: async (toolName) => {
      post("tool_result", { tool: "opencode", tool_name: toolName });
    },
    sessionStart: async () => {
      post("opencode_session_start", { tool: "opencode" });
    },
    sessionEnd: async () => {
      post("opencode_session_end", { tool: "opencode" });
    },
  };
};
