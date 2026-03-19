# Garmin Ingestion Workflow

## Current Human Flow

Today the Garmin retrieval process is:

1. log into Garmin Connect
2. open an activity
3. use the three-dot menu
4. export the FIT file
5. drop the raw file into `raw/garmin/inbox`

That is workable for now, but too manual to trust long term without a stronger ingestion pipeline.

## Immediate Goal

Reduce the fragile parts of the workflow without waiting for full Garmin automation.

The system should support:

- backfilling a date range such as the last 21 days
- dropping new FIT files into a flat raw inbox
- importing new files idempotently
- archiving successful files
- isolating failed files
- logging every run and file event

## Folder Layout

Recommended raw file layout:

- `raw/garmin/inbox`
- `raw/garmin/archive`
- `raw/garmin/failed`

Meaning:

- `inbox` is a flat drop zone where newly exported FIT files land
- `archive` stores files after successful import
- `failed` stores files that could not be parsed or imported

Users should not need to pre-organize inbox files by date.

## Modes

### Direct Import Mode

Use this for:

- one-time reprocessing from an alternate root
- one-time backfills
- sanity-checking a batch without moving files

Behavior:

- recursively scans the provided root
- imports new files
- logs imported, skipped, or failed outcomes
- leaves files in place

### Inbox Mode

Use this for:

- daily or frequent ongoing imports
- files exported manually from Garmin Connect into the flat inbox

Behavior:

- scans `raw/garmin/inbox`
- inspects file contents to determine activity date and type
- imports each file
- moves successful files into `raw/garmin/archive/YYYY-MM-DD/`
- moves failed files into `raw/garmin/failed/`
- logs all outcomes into the database

## Database Logging

The ingestion pipeline now logs:

- one row per ingestion run in `ingestion_runs`
- one row per file event in `ingestion_run_files`

This gives us visibility into:

- when a run started and finished
- how many files were scanned
- how many imported, skipped, or failed
- which files had issues
- which files were moved to archive or failed folders

## Suggested Workflow For You Right Now

### Backfill the last 21 days

1. export all desired activities from Garmin Connect
2. drop the raw FIT files into `raw/garmin/inbox`
3. run inbox-mode import
4. confirm rows landed in `activities`, `laps`, and `activity_samples`
5. confirm the files were archived

### Ongoing use

1. export new FIT file from Garmin Connect
2. drop it into `raw/garmin/inbox`
3. run inbox-mode import
4. review the dashboard or ingestion logs

## Commands

### Inbox import with file movement

```powershell
python import_garmin_fit.py --fit-root raw/garmin/inbox --run-mode inbox --archive-root raw/garmin/archive --failed-root raw/garmin/failed
```

### Force re-import

```powershell
python import_garmin_fit.py --fit-root raw/garmin/inbox --run-mode inbox --force
```

## Why This Matters

If retrieval breaks, we need to know exactly where the pipeline failed.

This ingestion design helps us answer:

- did the file ever arrive?
- did the importer see it?
- was it skipped as a duplicate?
- did parsing fail?
- where is the raw file now?

That makes the rest of the app worth trusting.
