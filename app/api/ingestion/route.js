import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { NextResponse } from "next/server";

import {
  getImporterScript,
  getInboxPreview,
  getLatestRunForMode,
  getPythonExecutable,
  getRecentIngestionEvents,
  getRecentIngestionRuns
} from "@/lib/ingestion";

export const dynamic = "force-dynamic";

const previewCachePath = path.join(process.cwd(), "temp", "ingestion_preview.json");

function writePreviewCache(fingerprint, preview) {
  fs.mkdirSync(path.dirname(previewCachePath), { recursive: true });
  fs.writeFileSync(
    previewCachePath,
    JSON.stringify(
      {
        fingerprint,
        generatedAt: new Date().toISOString(),
        preview
      },
      null,
      2
    ),
    "utf8"
  );
}

function clearPreviewCache() {
  if (fs.existsSync(previewCachePath)) {
    fs.unlinkSync(previewCachePath);
  }
}

export function GET() {
  return NextResponse.json({
    inbox: getInboxPreview(),
    runs: getRecentIngestionRuns(),
    events: getRecentIngestionEvents()
  });
}

function parseJsonStdout(stdoutText) {
  try {
    return JSON.parse(stdoutText);
  } catch {
    return null;
  }
}

function runImporter(args) {
  const command = [
    getImporterScript(),
    "--fit-root",
    "raw/garmin/inbox",
    "--timezone",
    "America/Chicago",
    ...args
  ];

  return spawnSync(getPythonExecutable(), command, {
    cwd: process.cwd(),
    encoding: "utf8"
  });
}

export async function POST(request) {
  const body = await request.json().catch(() => ({}));
  const action = body?.action;
  const preview = getInboxPreview();

  if (!["preview", "import"].includes(action)) {
    return NextResponse.json(
      {
        kind: "error",
        message: "Unknown ingestion action."
      },
      { status: 400 }
    );
  }

  if (action === "import" && preview.fileCount === 0) {
    const latestImport = getLatestRunForMode("inbox");
    return NextResponse.json({
      kind: "noop",
      message:
        "The staging area is already clear, so there was nothing to process.",
      preview,
      latestRun: latestImport
    });
  }

  if (action === "preview") {
    const latestPreview = getLatestRunForMode("inbox_preview");
    if (latestPreview?.notes?.includes(preview.fingerprint)) {
      return NextResponse.json({
        kind: "noop",
        message:
          "Nothing changed in the staging area since the last check, so the current report is still valid.",
        preview,
        latestRun: latestPreview
      });
    }

    const processResult = runImporter([
      "--run-mode",
      "inbox",
      "--preview",
      "--preview-json",
      "--notes",
      `fingerprint=${preview.fingerprint}`
    ]);
    const parsed = parseJsonStdout(processResult.stdout);
    if (processResult.status === 0 && parsed) {
      writePreviewCache(preview.fingerprint, parsed);
    }

    return NextResponse.json(
      {
        kind: processResult.status === 0 ? "preview" : "error",
        message:
          processResult.status === 0
            ? "Staging area check completed. Review the report below before processing."
            : "Preview failed. Check the error output below.",
        preview: parsed ?? preview,
        stdout: processResult.stdout,
        stderr: processResult.stderr
      },
      { status: processResult.status === 0 ? 200 : 500 }
    );
  }

  const processResult = runImporter([
    "--run-mode",
    "inbox",
    "--archive-root",
    "raw/garmin/archive",
    "--failed-root",
    "raw/garmin/failed",
    "--athlete-name",
    "D Hayashi",
    "--notes",
    `fingerprint=${preview.fingerprint}`
  ]);

  clearPreviewCache();
  const refreshedPreview = getInboxPreview();

  return NextResponse.json(
    {
      kind: processResult.status === 0 ? "import" : "error",
      message:
        processResult.status === 0
          ? "Processing completed. New files were imported and already-imported duplicates were cleared out of the staging area."
          : "Processing failed. Review the error output below and check the failed folder.",
      preview: refreshedPreview,
      stdout: processResult.stdout,
      stderr: processResult.stderr
    },
    { status: processResult.status === 0 ? 200 : 500 }
  );
}
