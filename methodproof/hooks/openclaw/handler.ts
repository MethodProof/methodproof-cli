// MethodProof hook for OpenClaw — captures agent messages and session lifecycle.
// Posts to local bridge or platform API. Fails silently (never blocks OpenClaw).

interface OpenClawEvent {
  type: string;
  action: string;
  sessionKey: string;
  timestamp: Date;
  messages: string[];
  context: Record<string, unknown>;
}

const handler = async (event: OpenClawEvent): Promise<void> => {
  if (!["command", "message"].includes(event.type)) return;

  const mode = process.env.METHODPROOF_MODE || "personal";
  const baseUrl =
    mode === "assessment"
      ? `${process.env.METHODPROOF_API_URL}/sessions/${process.env.METHODPROOF_SESSION_ID}`
      : "http://localhost:9877";

  let mpType: string;
  let metadata: Record<string, unknown>;

  if (event.type === "command") {
    mpType = "agent_session_event";
    metadata = {
      gateway: "openclaw",
      event_type: event.action,
      session_channel: (event.context?.commandSource as string) || "",
    };
  } else if (event.action === "received") {
    mpType = "agent_prompt";
    const content = ((event.context?.content as string) || "");
    metadata = {
      gateway: "openclaw",
      model: "",
      prompt_preview: content.slice(0, 200),
      prompt_length: content.length,
      session_channel: (event.context?.channelId as string) || "",
      tools_available: [],
    };
  } else if (event.action === "sent") {
    mpType = "agent_completion";
    const content = ((event.context?.content as string) || "");
    metadata = {
      gateway: "openclaw",
      model: "",
      response_preview: content.slice(0, 200),
      response_length: content.length,
      finish_reason: "stop",
      latency_ms: 0,
      step_count: 0,
    };
  } else {
    return;
  }

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 1000);
  try {
    await fetch(`${baseUrl}/events`, {
      method: "POST",
      signal: ac.signal,
      headers: {
        "Content-Type": "application/json",
        ...(mode === "assessment"
          ? { Authorization: `Bearer ${process.env.METHODPROOF_TOKEN}` }
          : {}),
      },
      body: JSON.stringify({
        events: [{ type: mpType, timestamp: Date.now() / 1000, metadata }],
      }),
    });
  } catch {
    // Silent — never block OpenClaw
  } finally {
    clearTimeout(timer);
  }
};

export default handler;
