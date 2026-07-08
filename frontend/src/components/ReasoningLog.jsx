import { useEffect, useRef } from "react";

function formatResult(result) {
  if (result === null || result === undefined) return "";
  if (typeof result === "string") return result;
  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return String(result);
  }
}

function formatTimestamp(ts) {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts ?? "";
  }
}

// One "channel strip" — a vertical lane for a single agent's reasoning trace.
export default function ReasoningLog({ laneKey, agentLabel, entries }) {
  const bodyRef = useRef(null);

  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  return (
    <div className={`channel-strip channel-strip--${laneKey}`}>
      <div className="channel-strip__header">
        <span className="channel-strip__name">{agentLabel}</span>
        <span className="channel-strip__count">{entries.length}</span>
      </div>
      <div className="channel-strip__body" ref={bodyRef}>
        {entries.length === 0 && <div className="channel-strip__empty">Awaiting signal…</div>}
        {entries.map((entry, idx) => (
          <div className="log-entry" key={`${entry.timestamp}-${idx}`}>
            <div className="log-entry__head">
              <span className="log-entry__action">{entry.action}</span>
              <span className="log-entry__timestamp">{formatTimestamp(entry.timestamp)}</span>
            </div>
            {entry.result !== undefined && entry.result !== "" && (
              <div className="log-entry__result">{formatResult(entry.result)}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
