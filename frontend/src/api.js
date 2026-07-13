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

// -- voice pipeline — purely additive I/O around the /chat endpoint above ---

// Sends the raw recorded audio blob as-is (whatever container MediaRecorder
// produced — webm, ogg, etc.) with its own mimeType as Content-Type, so the
// backend can read the bytes directly with no reliance on a file extension.
export async function transcribeAudio(audioBlob) {
  const response = await fetch("/api/voice/transcribe", {
    method: "POST",
    headers: { "Content-Type": audioBlob.type || "application/octet-stream" },
    body: audioBlob,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `Transcription failed with status ${response.status}`);
  }

  const data = await response.json();
  return data.transcribed_text ?? "";
}

// Returns an audio Blob (audio/mpeg) for the given text — only ever called
// with a reply /chat has already finished streaming in full.
export async function speakText(text) {
  const response = await fetch("/api/voice/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });

  if (!response.ok) {
    const errText = await response.text().catch(() => "");
    throw new Error(errText || `Speech synthesis failed with status ${response.status}`);
  }

  return response.blob();
}
