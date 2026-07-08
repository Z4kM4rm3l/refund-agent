import { useEffect, useRef, useState } from "react";

const PRESET_MESSAGES = [
  "I'd like to request a refund",
  "I need to return my purchase",
  "I want to speak with a manager",
  "This is unacceptable, I need my money back",
];

function TypingIndicator() {
  return (
    <div className="chat-row chat-row--agent">
      <div className="chat-bubble chat-bubble--agent">
        <span className="chat-agent-label">Agent Console</span>
        <div className="typing-indicator">
          <div className="typing-indicator__amp">
            <span className="typing-indicator__jack" />
            <span className="typing-indicator__ring" />
            <span className="typing-indicator__ring" />
            <span className="typing-indicator__ring" />
          </div>
          <span className="typing-indicator__text">
            processing<span className="dot">.</span>
            <span className="dot">.</span>
            <span className="dot">.</span>
          </span>
        </div>
      </div>
    </div>
  );
}

function formatTime(ts) {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

export default function ChatInterface({ messages, onSend, isTyping, disabled, isSending, streamingMessageId }) {
  const [inputValue, setInputValue] = useState("");
  const historyRef = useRef(null);
  const inputBlocked = disabled || isSending;

  useEffect(() => {
    const el = historyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, isTyping]);

  const handleSend = (text) => {
    const trimmed = (text ?? inputValue).trim();
    if (!trimmed || inputBlocked) return;
    onSend(trimmed);
    setInputValue("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") handleSend();
  };

  return (
    <div className="chat-interface">
      <div className="chat-history" ref={historyRef}>
        {messages.length === 0 && !isTyping && (
          <div className="chat-empty">
            {disabled
              ? "Select a customer above to start a support session."
              : "Say hello, or try a preset message below to kick off a refund conversation."}
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`chat-row chat-row--${m.role === "customer" ? "customer" : "agent"}`}>
            <div>
              <div
                className={`chat-bubble chat-bubble--${m.role === "customer" ? "customer" : "agent"} ${
                  m.role === "error" ? "chat-bubble--error" : ""
                }`}
              >
                {m.role !== "customer" && <span className="chat-agent-label">Agent Console</span>}
                {m.text}
                {m.id === streamingMessageId && <span className="stream-cursor" aria-hidden="true" />}
              </div>
              <div className="chat-meta">{formatTime(m.timestamp)}</div>
            </div>
          </div>
        ))}

        {isTyping && <TypingIndicator />}
      </div>

      <div className="chat-presets">
        {PRESET_MESSAGES.map((preset) => (
          <button
            key={preset}
            type="button"
            className="btn-preset"
            disabled={inputBlocked}
            onClick={() => handleSend(preset)}
          >
            {preset}
          </button>
        ))}
      </div>

      <div className="chat-input-row">
        <input
          type="text"
          placeholder={disabled ? "Select a customer first…" : isSending ? "Waiting for a reply…" : "Type a message…"}
          value={inputValue}
          disabled={inputBlocked}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          type="button"
          className="btn-pick"
          disabled={inputBlocked || !inputValue.trim()}
          onClick={() => handleSend()}
          aria-label="Send message"
        >
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M3 11.5L21 3l-5.5 18-4-7.5-7.5-4z" fill="#1a1204" />
          </svg>
        </button>
      </div>
    </div>
  );
}
