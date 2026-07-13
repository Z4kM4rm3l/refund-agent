import { useEffect, useRef, useState } from "react";
import { speakText, transcribeAudio } from "../api.js";

const PRESET_MESSAGES = [
  "I'd like to request a refund",
  "I need to return my purchase",
  "I want to speak with a manager",
  "This is unacceptable, I need my money back",
];

// Browsers report different native MediaRecorder mimeTypes; the transcribed
// text is shown in the input for this long before auto-sending, so the
// customer can see what was captured.
const TRANSCRIPT_PREVIEW_MS = 450;

const micSupported =
  typeof navigator !== "undefined" && !!navigator.mediaDevices && typeof window.MediaRecorder !== "undefined";

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

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="9" y="2" width="6" height="12" rx="3" fill="currentColor" />
      <path d="M5 11a7 7 0 0 0 14 0" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="12" y1="18" x2="12" y2="22" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="8" y1="22" x2="16" y2="22" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function SpeakerIcon({ muted }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M4 9v6h4l5 4V5L8 9H4z" fill="currentColor" />
      {muted ? (
        <>
          <line x1="16" y1="9" x2="21" y2="15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          <line x1="21" y1="9" x2="16" y2="15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </>
      ) : (
        <>
          <path d="M16.5 8.5a5 5 0 0 1 0 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
          <path d="M19 6a9 9 0 0 1 0 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" opacity="0.6" />
        </>
      )}
    </svg>
  );
}

export default function ChatInterface({ messages, onSend, isTyping, disabled, isSending, streamingMessageId }) {
  const [inputValue, setInputValue] = useState("");
  const historyRef = useRef(null);
  const textareaRef = useRef(null);
  const inputBlocked = disabled || isSending;

  // -- voice: speaker toggle + no-overlap playback ---------------------------
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const currentAudioRef = useRef(null);
  const messagesRef = useRef(messages);
  const prevStreamingIdRef = useRef(null);

  // -- voice: microphone capture ----------------------------------------------
  const [voiceState, setVoiceState] = useState("idle"); // idle | recording | transcribing
  const [voiceError, setVoiceError] = useState("");
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const voiceErrorTimeoutRef = useRef(null);

  useEffect(() => {
    const el = historyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, isTyping]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const stopCurrentAudio = () => {
    const audio = currentAudioRef.current;
    if (audio) {
      audio.pause();
      audio.src = "";
      currentAudioRef.current = null;
    }
  };

  // Every agent turn (not just final decisions — "what's your order number?"
  // deserves to be heard too) streams through the same reply_delta/final
  // event pair. streamingMessageId going from a real id back to null means
  // the "final" event has landed and the message's text is complete — never
  // fires mid-stream, never sends a partial sentence.
  useEffect(() => {
    const prevId = prevStreamingIdRef.current;
    prevStreamingIdRef.current = streamingMessageId;
    if (!prevId || streamingMessageId) return;

    const completed = messagesRef.current.find((m) => m.id === prevId);
    if (!completed || completed.role !== "agent" || !completed.text?.trim()) return;
    if (!voiceEnabled) return;

    (async () => {
      try {
        const audioBlob = await speakText(completed.text);
        stopCurrentAudio();
        const url = URL.createObjectURL(audioBlob);
        const audio = new Audio(url);
        currentAudioRef.current = audio;
        audio.addEventListener("ended", () => {
          URL.revokeObjectURL(url);
          if (currentAudioRef.current === audio) currentAudioRef.current = null;
        });
        await audio.play();
      } catch (err) {
        // Silent fallback — TTS is a nice-to-have, never lets a voice/API
        // hiccup break the (already-successful) text chat.
        console.error("Voice playback failed, continuing in text-only mode:", err);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streamingMessageId, voiceEnabled]);

  useEffect(() => () => stopCurrentAudio(), []);

  // Grows the textarea to fit its content (CSS max-height + overflow-y:auto
  // caps it at ~4 lines and takes over with internal scrolling beyond that).
  const autoResize = (el) => {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };

  const handleChange = (e) => {
    setInputValue(e.target.value);
    autoResize(e.target);
  };

  const handleSend = (text) => {
    const trimmed = (text ?? inputValue).trim();
    if (!trimmed || inputBlocked) return;

    // Clear the DOM node directly and *first* — synchronous, so the box
    // snaps back to single-line height and the placeholder reappears in the
    // same paint, before onSend ever kicks off the API call. Letting this
    // wait on the React state update (below) alone can show a stale frame.
    const el = textareaRef.current;
    if (el) {
      el.value = "";
      autoResize(el);
    }
    setInputValue("");

    onSend(trimmed);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
    // Shift+Enter falls through to the textarea's default behavior — a plain newline.
  };

  // -- voice: recording lifecycle ---------------------------------------------

  const showVoiceError = (message) => {
    setVoiceError(message);
    if (voiceErrorTimeoutRef.current) clearTimeout(voiceErrorTimeoutRef.current);
    voiceErrorTimeoutRef.current = window.setTimeout(() => setVoiceError(""), 6000);
  };

  const startRecording = async () => {
    setVoiceError("");
    stopCurrentAudio(); // don't talk over the customer once they start speaking

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const mimeType = recorder.mimeType || "audio/webm";
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });

        setVoiceState("transcribing");
        try {
          const text = await transcribeAudio(audioBlob);
          if (text.trim()) {
            // Populate the input so the customer sees what was captured,
            // then auto-send through the exact same path a typed message
            // takes — voice never bypasses the normal chat flow.
            setInputValue(text);
            if (textareaRef.current) {
              textareaRef.current.value = text;
              autoResize(textareaRef.current);
            }
            window.setTimeout(() => handleSend(text), TRANSCRIPT_PREVIEW_MS);
          } else {
            showVoiceError("Didn't catch that — please try again or type your message.");
          }
        } catch (err) {
          console.error("Transcription failed, falling back to text-only:", err);
          showVoiceError("Couldn't transcribe that — please type your message instead.");
        } finally {
          setVoiceState("idle");
        }
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setVoiceState("recording");
    } catch (err) {
      console.error("Microphone access failed:", err);
      showVoiceError("Microphone access was denied or unavailable — please type your message instead.");
      setVoiceState("idle");
    }
  };

  const stopRecording = () => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  };

  useEffect(
    () => () => {
      if (voiceErrorTimeoutRef.current) clearTimeout(voiceErrorTimeoutRef.current);
      stopRecording();
    },
    []
  );

  const handleMicClick = () => {
    if (voiceState === "recording") stopRecording();
    else if (voiceState === "idle") startRecording();
  };

  const micDisabled = inputBlocked || voiceState === "transcribing";

  return (
    <div className="chat-interface">
      <div className="chat-header">
        <span className="chat-header__label">Customer Chat</span>
        <button
          type="button"
          className={`btn-speaker ${voiceEnabled ? "btn-speaker--on" : "btn-speaker--off"}`}
          onClick={() => {
            setVoiceEnabled((v) => !v);
            if (voiceEnabled) stopCurrentAudio();
          }}
          aria-label={voiceEnabled ? "Mute agent voice replies" : "Unmute agent voice replies"}
          title={voiceEnabled ? "Voice replies: on" : "Voice replies: muted"}
        >
          <SpeakerIcon muted={!voiceEnabled} />
        </button>
      </div>

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

      {(voiceState === "recording" || voiceState === "transcribing" || voiceError) && (
        <div className="voice-status-row">
          {voiceState === "recording" && (
            <span className="voice-status voice-status--recording">
              <span className="voice-status__dot" /> Recording…
            </span>
          )}
          {voiceState === "transcribing" && (
            <span className="voice-status voice-status--transcribing">
              <span className="voice-status__spinner" /> Transcribing…
            </span>
          )}
          {voiceError && <span className="voice-status voice-status--error">{voiceError}</span>}
        </div>
      )}

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
        <textarea
          ref={textareaRef}
          rows={1}
          placeholder={disabled ? "Select a customer first…" : isSending ? "Waiting for a reply…" : "Type a message…"}
          value={inputValue}
          disabled={inputBlocked}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
        />
        {micSupported && (
          <button
            type="button"
            className={`btn-mic ${voiceState === "recording" ? "btn-mic--recording" : ""} ${
              voiceState === "transcribing" ? "btn-mic--transcribing" : ""
            }`}
            disabled={micDisabled}
            onClick={handleMicClick}
            aria-label={voiceState === "recording" ? "Stop recording" : "Record a voice message"}
            title={voiceState === "recording" ? "Stop recording" : "Record a voice message"}
          >
            <MicIcon />
          </button>
        )}
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
