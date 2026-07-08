import axios from "axios";

// vite.config.js proxies /api -> http://localhost:5000 (stripping the /api prefix)
const client = axios.create({
  baseURL: "/api",
  timeout: 60000,
});

export async function fetchCustomers() {
  const { data } = await client.get("/customers");
  return data.customers ?? [];
}

export async function fetchAdminLogs() {
  const { data } = await client.get("/admin/logs");
  return {
    refundRequests: data.refund_requests ?? [],
    reasoningLogs: data.reasoning_logs ?? [],
  };
}

// Streams POST /api/chat, whose response body is newline-delimited JSON (one
// event object per line). `onEvent` is called synchronously for each event as
// it arrives, so the caller can render the customer-facing reply token by
// token instead of waiting for the whole turn to finish. Uses raw fetch
// (not axios) because we need a readable byte stream, which axios's browser
// adapter doesn't expose in a portable way.
export async function streamChatMessage({ message, conversationId, customerId }, onEvent) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      customer_id: customerId,
    }),
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `Chat request failed with status ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const consumeLine = (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    try {
      onEvent(JSON.parse(trimmed));
    } catch (err) {
      console.error("Failed to parse stream event:", trimmed, err);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? ""; // last element may be an incomplete line — keep it buffered
    for (const line of lines) consumeLine(line);
  }
  consumeLine(buffer); // flush any trailing line with no terminating newline
}
