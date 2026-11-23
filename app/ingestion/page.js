import Link from "next/link";

import IngestionConsole from "@/app/ingestion/IngestionConsole";
import {
  getRecentIngestionEvents,
  getRecentIngestionRuns,
  getSyncStatus
} from "@/lib/ingestion";
import { formatTimestampForDisplay } from "@/lib/format";

export const metadata = {
  title: "Garmin Sync | move2Zero"
};

export const dynamic = "force-dynamic";

export default function IngestionPage() {
  const status = getSyncStatus();
  const runs = getRecentIngestionRuns();
  const events = getRecentIngestionEvents();
  const { lastSync, keyExpiry } = status;
  const keyDays = keyExpiry && !keyExpiry.invalid ? keyExpiry.daysLeft : null;

  return (
    <main className="page-shell">
      <section className="hero">
        <h1>Garmin Sync</h1>
        <p>
          New activities are pulled from Garmin and imported automatically. Use the
          button to sync right now. You can still drop a .fit file into{" "}
          <code>{status.inboxPath}</code> and the next sync will import it.
        </p>
      </section>

      <div className="toolbar">
        <Link className="button-link" href="/">
          Dashboard
        </Link>
        <Link className="button-link" href="/api/ingestion">
          Status API
        </Link>
      </div>

      <IngestionConsole />

      <section className="stats-grid">
        <article className="card">
          <div className="metric-label">Last sync</div>
          <div className="metric-value" style={{ fontSize: "1.4rem" }}>
            {lastSync ? (lastSync.ok ? "Succeeded" : "Needs attention") : "Not run yet"}
          </div>
          <p className="muted">
            {lastSync
              ? `${lastSync.message} ${formatTimestampForDisplay(lastSync.finished_at)} (${lastSync.trigger}).`
              : "Press the button, or wait for the next hourly run."}
          </p>
        </article>
        <article className="card">
          <div className="metric-label">Automatic sync</div>
          <div className="metric-value" style={{ fontSize: "1.4rem" }}>
            {status.scheduleInstalled ? "On" : "Off"}
          </div>
          <p className="muted">
            {status.scheduleInstalled
              ? "Runs every hour, at login, and when the Mac wakes."
              : "Run scripts/install_sync_schedule.sh to sync automatically every hour."}
          </p>
        </article>
        <article className="card">
          <div className="metric-label">Garmin key</div>
          <div className="metric-value" style={{ fontSize: "1.4rem" }}>
            {keyDays === null
              ? "Expiry not set"
              : keyDays < 0
                ? "Expired"
                : `${keyDays} day${keyDays === 1 ? "" : "s"} left`}
          </div>
          <p className="muted">
            {keyExpiry?.invalid
              ? `GARMIN_KEY_EXPIRES in .env must look like 2027-01-31 (found "${keyExpiry.raw}").`
              : keyDays === null
                ? "Garmin does not report this. Copy the expiry date from Garmin Connect into .env as GARMIN_KEY_EXPIRES=YYYY-MM-DD to get a warning."
                : keyDays <= 14
                  ? `Expires ${keyExpiry.date}. Generate a new key in Garmin Connect and update .env.`
                  : `Expires ${keyExpiry.date}. You will be warned two weeks before.`}
          </p>
        </article>
        <article className="card">
          <div className="metric-label">Waiting in inbox</div>
          <div className="metric-value" style={{ fontSize: "1.4rem" }}>
            {status.inboxCount}
          </div>
          <p className="muted">
            {status.inboxCount === 0
              ? "Nothing is waiting. That is the healthy state."
              : "Dropped by hand or left by an interrupted run. The next sync imports them."}
          </p>
        </article>
        <article className="card">
          <div className="metric-label">Failed files</div>
          <div className="metric-value" style={{ fontSize: "1.4rem" }}>
            {status.failedCount}
          </div>
          <p className="muted">
            {status.failedCount === 0
              ? "No file has failed to import."
              : `Could not be imported. They were moved to ${status.failedPath}.`}
          </p>
        </article>
      </section>

      <section className="section">
        <div className="section-header">
          <div>
            <h2>Sync history</h2>
            <p>One row per import. Anything that fails shows up in the failed column.</p>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Checked</th>
                <th>Imported</th>
                <th>Duplicates cleared</th>
                <th>Failed</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>{run.id}</td>
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
            <h2>Recent file activity</h2>
            <p>File-level history, useful when something fails or gets moved.</p>
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
                <th>When</th>
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
