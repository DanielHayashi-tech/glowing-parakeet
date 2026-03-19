import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { queryAll, queryOne } from "@/lib/db";
import {
  formatIsoDateToDisplay,
  formatTimestampForDisplay,
  isoDateInTimezone,
  titleizeActivityType
} from "@/lib/format";

const inboxRoot = path.join(process.cwd(), "raw", "garmin", "inbox");
const previewCachePath = path.join(process.cwd(), "temp", "ingestion_preview.json");
const pythonExecutable = "python";
const importerScript = path.join(process.cwd(), "import_garmin_fit.py");

function listFitFiles(rootDir) {
  const files = [];

  function walk(currentDir) {
    for (const entry of fs.readdirSync(currentDir, { withFileTypes: true })) {
      if (entry.name === ".gitkeep") {
        continue;
      }

      const fullPath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        walk(fullPath);
      } else if (entry.isFile() && entry.name.toLowerCase().endsWith(".fit")) {
        files.push(fullPath);
      }
    }
  }

  if (fs.existsSync(rootDir)) {
    walk(rootDir);
  }

  return files.sort();
}

function fileHash(filePath) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filePath));
  return hash.digest("hex");
}

function makeInboxFingerprint(files) {
  const hash = crypto.createHash("sha256");
  for (const file of files) {
    hash.update(file.filePath);
    hash.update(file.fileHash);
  }
  return hash.digest("hex");
}

function loadPreviewCache(expectedFingerprint) {
  if (!fs.existsSync(previewCachePath)) {
    return null;
  }

  try {
    const parsed = JSON.parse(fs.readFileSync(previewCachePath, "utf8"));
    if (!parsed || parsed.fingerprint !== expectedFingerprint || !parsed.preview) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function normalizeFolderDate(folderName) {
  const match = /^(\d{1,2})-(\d{1,2})-(\d{4})$/.exec(folderName);
  if (!match) {
    return null;
  }

  const [, mm, dd, yyyy] = match;
  return `${yyyy}-${mm.padStart(2, "0")}-${dd.padStart(2, "0")}`;
}

function dateHintFromFilename(filename) {
  const parts = filename.split("__", 2);
  if (parts.length < 2) {
    return null;
  }
  return normalizeFolderDate(parts[0]);
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

export function getInboxPreview() {
  const baseFiles = listFitFiles(inboxRoot).map((fullPath) => {
    const relativePath = path.relative(process.cwd(), fullPath);
    const fileName = path.basename(fullPath);
    const hash = fileHash(fullPath);
    const known = queryOne(
      `
        SELECT
          source_file_id,
          source_status,
          file_path,
          imported_at,
          latest_event_type,
          latest_event_at,
          activity_id,
          activity_type,
          started_at_utc,
          activity_date_utc,
          activity_timezone
        FROM vw_source_file_current_state
        WHERE file_hash = ? OR file_path = ?
        LIMIT 1
      `,
      [hash, relativePath]
    );
    const dateHint = dateHintFromFilename(fileName);
    return {
      filePath: relativePath,
      fileName,
      dateHint,
      fileHash: hash,
      duplicateStatus: known?.source_status ?? "new",
      knownFilePath: known?.file_path ?? null,
      importedAt: known?.imported_at ?? null,
      latestEventType: known?.latest_event_type ?? null,
      latestEventAt: known?.latest_event_at ?? null,
      latestEventAtDisplay: known?.latest_event_at
        ? formatTimestampForDisplay(known.latest_event_at)
        : null,
      activityId: known?.activity_id ?? null,
      activityType: known?.activity_type ?? null,
      activityDate:
        known?.started_at_utc && known?.activity_timezone
          ? isoDateInTimezone(known.started_at_utc, known.activity_timezone)
          : known?.activity_date_utc ?? null,
      activityDateDisplay:
        known?.started_at_utc && known?.activity_timezone
          ? formatIsoDateToDisplay(
              isoDateInTimezone(known.started_at_utc, known.activity_timezone)
            )
          : known?.activity_date_utc
            ? formatIsoDateToDisplay(known.activity_date_utc)
            : null,
      isKnown: Boolean(known)
    };
  });
  const fingerprint = makeInboxFingerprint(baseFiles);
  const cachedPreview = loadPreviewCache(fingerprint);
  const previewRowsByHash = new Map(
    (cachedPreview?.preview?.files ?? []).map((row) => [row.file_hash, row])
  );
  const files = baseFiles.map((file) => {
    const previewRow = previewRowsByHash.get(file.fileHash);
    if (!previewRow) {
      return file;
    }

    return {
      ...file,
      duplicateStatus: previewRow.duplicate_status ?? file.duplicateStatus,
      importedAt: previewRow.imported_at ?? file.importedAt,
      activityType: previewRow.activity_type ?? file.activityType,
      activityDate: previewRow.activity_date ?? file.activityDate,
      activityDateDisplay: previewRow.activity_date
        ? formatIsoDateToDisplay(previewRow.activity_date)
        : file.activityDateDisplay,
      warningMessages: previewRow.warnings ?? [],
      errorMessages: previewRow.errors ?? [],
      sessionCount: previewRow.session_count ?? null,
      hasPreviewData: true
    };
  });

  const byDate = new Map();
  for (const file of files) {
    const dateKey = file.activityDate ?? file.dateHint ?? "needs_review";
    if (!byDate.has(dateKey)) {
      byDate.set(dateKey, {
        dateKey,
        dateDisplay:
          dateKey === "needs_review"
            ? "Needs Check"
            : formatIsoDateToDisplay(dateKey),
        totalFiles: 0,
        newFiles: 0,
        importedFiles: 0,
        activityTypes: new Set(),
        files: []
      });
    }

    const group = byDate.get(dateKey);
    group.totalFiles += 1;
    if (file.isKnown) {
      group.importedFiles += 1;
    } else {
      group.newFiles += 1;
    }
    if (file.activityType) {
      group.activityTypes.add(titleizeActivityType(file.activityType));
    }
    group.files.push(file);
  }

  return {
    inboxRoot: path.relative(process.cwd(), inboxRoot),
    fileCount: files.length,
    newCount: files.filter((file) => !file.isKnown).length,
    knownCount: files.filter((file) => file.isKnown).length,
    fingerprint,
    hasParsedPreview: Boolean(cachedPreview?.preview),
    previewGeneratedAt: cachedPreview?.generatedAt ?? null,
    previewGeneratedAtDisplay: cachedPreview?.generatedAt
      ? formatTimestampForDisplay(cachedPreview.generatedAt)
      : null,
    files,
    groupedDates: Array.from(byDate.values())
      .map((group) => ({
        ...group,
        activityTypes: Array.from(group.activityTypes).sort()
      }))
      .sort((a, b) => (a.dateKey < b.dateKey ? 1 : -1))
  };
}

export function getLatestRunForMode(runModePrefix) {
  return queryOne(
    `
      SELECT *
      FROM ingestion_runs
      WHERE run_mode LIKE ?
      ORDER BY id DESC
      LIMIT 1
    `,
    [`${runModePrefix}%`]
  );
}

export function getPythonExecutable() {
  return pythonExecutable;
}

export function getImporterScript() {
  return importerScript;
}
