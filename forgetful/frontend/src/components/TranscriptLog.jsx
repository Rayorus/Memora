// components/TranscriptLog.jsx
// Shows the rolling live transcript and auto-summarization status.

import React, { useEffect, useRef } from "react";

export default function TranscriptLog({ entries }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  return (
    <div className="card" style={{ height: 180, overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.3rem" }}>
      <p style={{ fontSize: "0.72rem", color: "var(--muted)", marginBottom: "0.35rem", letterSpacing: "0.05em" }}>
        Transcript
      </p>
      {entries.length === 0 ? (
        <p style={{ fontSize: "0.82rem", color: "var(--muted)", margin: "auto" }}>Listening…</p>
      ) : (
        entries.map((e, i) => (
          <div key={i} className="fade-in" style={{ marginBottom: "0.2rem", lineHeight: 1.3 }}>
            <span style={{ fontSize: "0.73rem", color: "var(--muted)", marginRight: "0.45rem" }}>
              {new Date(e.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
            <span style={{ fontSize: "0.84rem", color: "var(--text)" }}>{e.text}</span>
          </div>
        ))
      )}
      <div ref={bottomRef} />
    </div>
  );
}
