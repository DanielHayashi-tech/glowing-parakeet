# Garmin Ingestion Workflow

## The Flow

One command does everything, whether you press the button, run it by hand, or the nightly job runs it:

```bash
python run_sync.py
```

1. **Fetch activities.** `sync_garmin_api.py` asks the Garmin Personal API for the newest activities
   and downloads the original FIT file for each one it does not already have, into `raw/garmin/inbox`.
2. **Import.** `import_garmin_fit.py` reads every file in the inbox, writes `activities`, `laps`, and
   `activity_samples`, moves imported files to `raw/garmin/archive/YYYY-MM-DD/`, and moves files it
   cannot parse to `raw/garmin/failed/`.
3. **Refresh wellness.** `sync_garmin_wellness.py` re-reads the last 3 days of sleep, HRV, heart rate,
   and daily summary (30 days on the first run) and writes `wellness_daily` and `wellness_raw`.
4. **Record the result** in `temp/last_sync.json`, which the Garmin Sync page shows.

Details of the API itself are in `garmin-personal-api-notes.md`.

## Folder Layout

- `raw/garmin/inbox` files waiting to be imported. A flat drop zone; no sub-folders or date naming needed.
- `raw/garmin/archive` every successfully imported file, grouped by activity date. This is the raw
  record the database can be rebuilt from.
- `raw/garmin/failed` files that could not be imported.

## Behavior Worth Knowing

- **Idempotent.** A file is recognised by its content hash and path, so syncing twice never duplicates
  an activity. An already-imported file found in the inbox is cleared and archived as a duplicate.
- **Manual fallback.** A `.fit` file dropped into the inbox is imported on the next sync, even when the
  Garmin step fails (for example an expired key).
- **Failures are separate.** A rejected key, a failed import, and a failed wellness day are each reported
  in the summary and the notification; one does not hide another.
- **Only one sync at a time.** A lock file stops the button and the nightly job colliding.

## Database Logging

- one row per import run in `ingestion_runs`
- one row per file event in `ingestion_run_files`

This shows when a run started and finished, how many files were scanned, imported, skipped, or failed,
and which files were archived or moved to `failed`.

## Importing Files From Somewhere Else

```bash
# one-off import from any folder, leaving files in place
python import_garmin_fit.py --fit-root path/to/fit/files

# preview what would happen without importing
python import_garmin_fit.py --fit-root path/to/fit/files --preview
```

Use `--run-mode inbox --archive-root raw/garmin/archive --failed-root raw/garmin/failed` to also move
files after processing, which is what `run_sync.py` does.
