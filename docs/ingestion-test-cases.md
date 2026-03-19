# Ingestion Test Cases

## Purpose

Create repeatable test scenarios in `raw/garmin/inbox` so the ingestion UI can
be validated without manually hunting for specific FIT files every time.

Important model:

- inbox is a flat raw drop zone
- users do not organize files into date folders before import
- ingestion reads raw files, validates them, and organizes archive output later

## Script

Use:

```powershell
python scripts/stage_ingestion_test_cases.py --case all
```

Or stage one case at a time:

```powershell
python scripts/stage_ingestion_test_cases.py --case wrong-folder-date
python scripts/stage_ingestion_test_cases.py --case duplicate-known
python scripts/stage_ingestion_test_cases.py --case mixed-day
```

## Cases

### `wrong-folder-date`

Copies a FIT file into inbox with a filename hint that intentionally suggests
the wrong day.

Expected behavior:

- preview warns that the inbox date hint and activity date do not match
- staging area still shows the file
- processing should still work, but the warning should be visible

### `duplicate-known`

Copies an already imported FIT file back into inbox.

Expected behavior:

- preview marks it as already imported
- processing should clear it back out of staging without creating a duplicate activity row

### `mixed-day`

Copies multiple activities into inbox that belong to overlapping dates and
different activity types.

Expected behavior:

- staging area groups files by detected activity day in the UI
- file detail still shows each underlying FIT file

## Cleanup

Process staging from the UI or run:

```powershell
python import_garmin_fit.py --fit-root raw/garmin/inbox --run-mode inbox --archive-root raw/garmin/archive --failed-root raw/garmin/failed --athlete-name "D Hayashi" --timezone America/Chicago
```
