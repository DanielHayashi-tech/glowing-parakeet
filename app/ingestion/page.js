import Link from "next/link";

import IngestionConsole from "@/app/ingestion/IngestionConsole";
import {
  getInboxPreview,
  getRecentIngestionEvents,
  getRecentIngestionRuns
} from "@/lib/ingestion";
import {
  formatIsoDateToDisplay,
  formatTimestampForDisplay,
  titleizeActivityType
} from "@/lib/format";

export const metadata = {
  title: "Ingestion | move2Zero"
};

export const dynamic = "force-dynamic";

export default function IngestionPage() {
  const runs = getRecentIngestionRuns();
  const events = getRecentIngestionEvents();
  const inbox = getInboxPreview();
  const stagingIsClear = inbox.fileCount === 0;

  return (
    <main className="page-shell">
      <section className="hero">
        <h1>Garmin Staging Area</h1>
        <p>
          Drop exported FIT files straight into inbox,
          check the staging area, then process it. The goal here is simple:
          keep staging empty unless something needs attention.
        </p>
      </section>

      <div className="toolbar">
        <Link className="button-link" href="/">
          Dashboard
        </Link>
        <Link className="button-link" href="/api/ingestion">
          Ingestion API
        </Link>
      </div>

      <IngestionConsole initialPreview={inbox} />

      <section className="section">
        <div className="card">
          <div className="metric-label">
            {stagingIsClear ? "Staging Area Status" : "Staging Area Needs Attention"}
          </div>
          <div className="metric-value">
            {stagingIsClear ? "Clear" : `${inbox.fileCount} file${inbox.fileCount === 1 ? "" : "s"}`}
          </div>
          <p className="muted">
            {stagingIsClear
              ? "Nothing is waiting in inbox. That is the healthy state."
              : `${inbox.newCount} new file${inbox.newCount === 1 ? "" : "s"} ready to import, ${inbox.knownCount} already-imported file${inbox.knownCount === 1 ? "" : "s"} still sitting in staging.`}
          </p>
          {!stagingIsClear && !inbox.hasParsedPreview ? (
            <p className="muted">
              This is a raw inbox count. Run <strong>Check Staging Area</strong> to detect
              activity dates, activity types, warnings, and bad files before processing.
            </p>
          ) : null}
          {inbox.hasParsedPreview && inbox.previewGeneratedAt ? (
            <p className="muted">
              Last staging check: {inbox.previewGeneratedAtDisplay}
            </p>
          ) : null}
        </div>
      </section>

      <section className="section">
        <div className="section-header">
          <div>
            <h2>Staging Area</h2>
            <p>
              This is the first thing to check. If the staging area is empty,
              there is nothing left to process. Before you run a check, this table
              shows a staging summary. After a check, it shows detected activity dates.
            </p>
          </div>
        </div>
        {stagingIsClear ? (
          <div className="empty-state">
            Staging area is empty. No files are waiting to be checked or imported.
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{inbox.hasParsedPreview ? "Detected Date" : "Staging Bucket"}</th>
                  <th>Total Files</th>
                  <th>Ready To Import</th>
                  <th>Already Imported</th>
                  <th>{inbox.hasParsedPreview ? "Activity Types" : "What We Know"}</th>
                </tr>
              </thead>
              <tbody>
                {inbox.groupedDates.map((group) => (
                  <tr key={group.dateKey}>
                    <td>{group.dateDisplay}</td>
                    <td>{group.totalFiles}</td>
                    <td>{group.newFiles}</td>
                    <td>{group.importedFiles}</td>
                    <td>
                      {inbox.hasParsedPreview
                        ? group.activityTypes.length
                          ? group.activityTypes.join(", ")
                          : "-"
                        : group.dateKey === "needs_review"
                          ? "Needs a staging check before dates/types can be shown"
                          : "Date hint from filename"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="section">
        <div className="section-header">
          <div>
            <h2>File Detail</h2>
            <p>
              Use this when something needs attention: wrong date hint,
              duplicate leftovers, parse issues, or files that still need a check.
            </p>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Date Hint</th>
                <th>File</th>
                <th>Detected Activity</th>
                <th>Warnings</th>
                <th>JSON</th>
                <th>Imported At</th>
                <th>Latest Event</th>
              </tr>
            </thead>
            <tbody>
              {inbox.files.map((file) => (
                <tr key={file.filePath}>
                  <td>
                    <span className="pill">
                      {file.duplicateStatus === "new" ? "ready" : "already imported"}
                    </span>
                  </td>
                  <td>
                    {file.dateHint ? formatIsoDateToDisplay(file.dateHint) : "-"}
                  </td>
                  <td>{file.fileName}</td>
                  <td>
                    {file.activityType
                      ? `${titleizeActivityType(file.activityType)} (${file.activityDateDisplay ?? "unknown"})`
                      : file.hasPreviewData
                        ? "Could not detect activity"
                        : "Run check to detect"}
                  </td>
                  <td>
                    {file.errorMessages?.length
                      ? file.errorMessages.join(" | ")
                      : file.warningMessages?.length
                        ? file.warningMessages.join(" | ")
                        : "-"}
                  </td>
                  <td>
                    <Link
                      className="button-link"
                      href={`/api/fit-json?filePath=${encodeURIComponent(file.filePath)}`}
                    >
                      Download
                    </Link>
                  </td>
                  <td>{file.importedAt ?? "-"}</td>
                  <td>
                    {file.latestEventType
                      ? `${file.latestEventType}${file.latestEventAtDisplay ? ` @ ${file.latestEventAtDisplay}` : ""}`
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section">
        <div className="section-header">
          <div>
            <h2>Processing History</h2>
            <p>Simple ledger of recent checks and imports.</p>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Action</th>
                <th>Status</th>
                <th>Scanned</th>
                <th>Imported</th>
                <th>Left Alone</th>
                <th>Failed</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>{run.id}</td>
                  <td>{run.run_mode.replaceAll("_", " ")}</td>
                  <td>{run.status}</td>
                  <td>{run.scanned_file_count}</td>
                  <td>{run.imported_count}</td>
                  <td>{run.skipped_count}</td>
                  <td>{run.failed_count}</td>
                  <td>{formatTimestampForDisplay(run.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section">
        <div className="section-header">
          <div>
            <h2>Recent Problems And Moves</h2>
            <p>File-level history for when something goes wrong or gets moved.</p>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Event</th>
                <th>Path</th>
                <th>Message</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td>{event.ingestion_run_id}</td>
                  <td>{event.event_type}</td>
                  <td>{event.file_path}</td>
                  <td>{event.message ?? "-"}</td>
                  <td>{formatTimestampForDisplay(event.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
