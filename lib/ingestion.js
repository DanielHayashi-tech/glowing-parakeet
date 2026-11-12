import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { queryAll, queryOne } from "@/lib/db";

const rawRoot = path.join(process.cwd(), "raw", "garmin");
const inboxRoot = path.join(rawRoot, "inbox");
const failedRoot = path.join(rawRoot, "failed");
const pythonExecutable = "python";
const syncScript = path.join(process.cwd(), "run_sync.py");
const lastSyncPath = path.join(process.cwd(), "temp", "last_sync.json");
const nightlyAgentPath = path.join(
  os.homedir(),
  "Library",
  "LaunchAgents",
  "com.move2zero.nightly-sync.plist"
);

function countFitFiles(rootDir) {
  if (!fs.existsSync(rootDir)) {
    return 0;
  }

  let count = 0;
  for (const entry of fs.readdirSync(rootDir, { withFileTypes: true })) {
    const fullPath = path.join(rootDir, entry.name);
    if (entry.isDirectory()) {
      count += countFitFiles(fullPath);
    } else if (entry.isFile() && entry.name.toLowerCase().endsWith(".fit")) {
      count += 1;
    }
  }
  return count;
}

export function getRecentIngestionRuns() {
  return queryAll(
    `
      SELECT
        id,
        source_type,
        run_mode,
        started_at,
        completed_at,
        status,
        scanned_file_count,
        imported_count,
        skipped_count,
        failed_count,
        notes
      FROM ingestion_runs
      ORDER BY id DESC
      LIMIT 20
    `
  );
}

export function getRecentIngestionEvents() {
  return queryAll(
    `
      SELECT
        irf.id,
        irf.ingestion_run_id,
        irf.file_path,
        irf.file_hash,
        irf.event_type,
        irf.message,
        irf.created_at
      FROM ingestion_run_files irf
      ORDER BY irf.id DESC
      LIMIT 50
    `
  );
}

// Written by run_sync.py after every run, whether started by the button or the nightly job.
function readLastSync() {
  try {
    return JSON.parse(fs.readFileSync(lastSyncPath, "utf8"));
  } catch {
    return null;
  }
}

// The key's expiry is copied from Garmin Connect into .env (GARMIN_KEY_EXPIRES=YYYY-MM-DD),
// since Garmin does not expose it through the API. Next.js loads .env for us.
function readKeyExpiry() {
  const raw = (process.env.GARMIN_KEY_EXPIRES ?? "").trim();
  if (!raw) {
    return null;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw) || Number.isNaN(Date.parse(raw))) {
    return { invalid: true, raw };
  }
  const endOfDay = new Date(`${raw}T23:59:59`);
  return {
    date: raw,
    daysLeft: Math.ceil((endOfDay.getTime() - Date.now()) / 86_400_000) - 1
  };
}

// Cheap status for the sync page: no parsing or hashing, just counts.
export function getSyncStatus() {
  return {
    lastSync: readLastSync(),
    nightlyInstalled: fs.existsSync(nightlyAgentPath),
    keyExpiry: readKeyExpiry(),
    inboxPath: path.relative(process.cwd(), inboxRoot),
    failedPath: path.relative(process.cwd(), failedRoot),
    inboxCount: countFitFiles(inboxRoot),
    failedCount: countFitFiles(failedRoot),
    latestRun: queryOne(
      `
        SELECT id, status, started_at, completed_at, scanned_file_count,
               imported_count, skipped_count, failed_count
        FROM ingestion_runs
        WHERE run_mode = 'inbox'
        ORDER BY id DESC
        LIMIT 1
      `
    )
  };
}

export function getPythonExecutable() {
  return pythonExecutable;
}

export function getSyncScript() {
  return syncScript;
}
