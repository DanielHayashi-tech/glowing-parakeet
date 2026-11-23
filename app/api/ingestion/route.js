import { spawnSync } from "node:child_process";

import { NextResponse } from "next/server";

import {
  getPythonExecutable,
  getRecentIngestionEvents,
  getRecentIngestionRuns,
  getSyncScript,
  getSyncStatus
} from "@/lib/ingestion";

export const dynamic = "force-dynamic";

// A first backfill can take a few minutes (one download per activity).
const SYNC_TIMEOUT_MS = 20 * 60 * 1000;

export function GET() {
  return NextResponse.json({
    status: getSyncStatus(),
    runs: getRecentIngestionRuns(),
    events: getRecentIngestionEvents()
  });
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// run_sync.py does the work (fetch from Garmin, import, archive) so the button
// and the scheduled job behave identically. This route only runs it and reports.
function runSync() {
  const processResult = spawnSync(getPythonExecutable(), [getSyncScript(), "--json"], {
    cwd: process.cwd(),
    encoding: "utf8",
    timeout: SYNC_TIMEOUT_MS
  });
  const result = parseJson(processResult.stdout);

  if (processResult.error?.code === "ETIMEDOUT") {
    return NextResponse.json(
      {
        kind: "error",
        message:
          "Sync timed out. Anything already downloaded is safe; run it again to continue."
      },
      { status: 500 }
    );
  }

  if (!result) {
    return NextResponse.json(
      {
        kind: "error",
        message: "Sync failed to start. Check the error output below.",
        stderr: processResult.stderr
      },
      { status: 500 }
    );
  }

  return NextResponse.json(
    {
      kind: result.ok ? "sync" : "error",
      message: result.message,
      stdout: (result.log ?? []).join("\n"),
      stderr: processResult.stderr
    },
    { status: result.ok ? 200 : 500 }
  );
}

export async function POST(request) {
  const body = await request.json().catch(() => ({}));

  if (body?.action !== "sync") {
    return NextResponse.json(
      { kind: "error", message: "Unknown action." },
      { status: 400 }
    );
  }

  return runSync();
}
