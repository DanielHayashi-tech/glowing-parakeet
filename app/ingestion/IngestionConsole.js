"use client";

import { useState, useTransition } from "react";

function RenderActionResult({ result }) {
  if (!result) {
    return null;
  }

  return (
    <section className="section">
      <div className="card">
        <div className="metric-label">
          {result.kind === "error" ? "Sync needs attention" : "Sync finished"}
        </div>
        <p style={{ marginTop: 8 }}>{result.message}</p>
        {result.stdout ? <pre style={{ marginTop: "14px" }}>{result.stdout}</pre> : null}
        {result.stderr ? (
          <pre style={{ marginTop: "14px", background: "#3a1717" }}>{result.stderr}</pre>
        ) : null}
      </div>
    </section>
  );
}

export default function IngestionConsole() {
  const [result, setResult] = useState(null);
  const [isPending, startTransition] = useTransition();

  function runSync() {
    startTransition(async () => {
      const response = await fetch("/api/ingestion", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "sync" })
      });
      const payload = await response.json();
      setResult(payload);
      // Reloading would wipe the message, so keep errors (like an expired
      // Garmin key) on screen.
      if (payload.kind !== "error") {
        window.location.reload();
      }
    });
  }

  return (
    <>
      <div className="toolbar">
        <button
          className="button-link primary"
          disabled={isPending}
          onClick={runSync}
          type="button"
        >
          {isPending ? "Syncing..." : "Sync from Garmin now"}
        </button>
      </div>

      <RenderActionResult result={result} />
    </>
  );
}
