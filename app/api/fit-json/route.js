import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { NextResponse } from "next/server";

import { getPythonExecutable } from "@/lib/ingestion";

export const dynamic = "force-dynamic";

const fitSummaryScript = path.join(process.cwd(), "fit_summary.py");

function resolveFitPath(rawPath) {
  if (!rawPath) {
    return null;
  }

  const normalized = path.normalize(rawPath);
  const resolved = path.resolve(process.cwd(), normalized);
  if (!resolved.startsWith(process.cwd())) {
    return null;
  }
  if (!resolved.toLowerCase().endsWith(".fit")) {
    return null;
  }
  if (!fs.existsSync(resolved)) {
    return null;
  }
  return resolved;
}

export function GET(request) {
  const { searchParams } = new URL(request.url);
  const filePath = resolveFitPath(searchParams.get("filePath"));

  if (!filePath) {
    return NextResponse.json(
      { error: "FIT file not found or path is invalid." },
      { status: 400 }
    );
  }

  const processResult = spawnSync(
    getPythonExecutable(),
    [fitSummaryScript, "--json", "--timezone", "America/Chicago", filePath],
    {
      cwd: process.cwd(),
      encoding: "utf8"
    }
  );

  if (processResult.status !== 0) {
    return NextResponse.json(
      {
        error: "Failed to convert FIT file to JSON.",
        stderr: processResult.stderr
      },
      { status: 500 }
    );
  }

  const downloadName = `${path.basename(filePath, ".fit")}.json`;
  return new NextResponse(processResult.stdout, {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Disposition": `attachment; filename="${downloadName}"`
    }
  });
}
