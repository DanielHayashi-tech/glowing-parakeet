"use client";

import { useState, useTransition } from "react";

function RenderActionResult({ result }) {
  if (!result) {
    return null;
  }

  return (
    <section className="section">
      <div className="section-header">
        <div>
          <h2>Latest Action</h2>
          <p>Real-time feedback from the ingestion controls.</p>
        </div>
      </div>
      <div className="card">
        <div className="metric-label">Latest Result</div>
        <div className="metric-value" style={{ fontSize: "1.4rem" }}>
          {result.kind}
        </div>
        <p className="muted">{result.message}</p>
        {result.stdout ? (
          <pre style={{ marginTop: "14px" }}>{result.stdout}</pre>
        ) : null}
        {result.stderr ? (
          <pre style={{ marginTop: "14px", background: "#3a1717" }}>
            {result.stderr}
          </pre>
        ) : null}
      </div>
    </section>
  );
}

export default function IngestionConsole({ initialPreview }) {
  const [result, setResult] = useState(null);
  const [isPending, startTransition] = useTransition();

  function runAction(action) {
    startTransition(async () => {
      const response = await fetch("/api/ingestion", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ action })
      });
      const payload = await response.json();
      setResult(payload);
      window.location.reload();
    });
  }

  return (
    <>
      <div className="toolbar">
        <button
          className="button-link primary"
          disabled={isPending}
          onClick={() => runAction("preview")}
          type="button"
        >
          {isPending ? "Working..." : "Check Staging Area"}
        </button>
        <button
          className="button-link accent"
          disabled={isPending}
          onClick={() => runAction("import")}
          type="button"
        >
          {isPending ? "Working..." : "Process Staging Area"}
        </button>
      </div>

      <RenderActionResult result={result} />
    </>
  );
}
