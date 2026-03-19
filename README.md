# move2Zero

Local training data hub built around Garmin FIT ingestion, a SQLite database,
and a Next.js dashboard.

## What This Repo Does

- ingests raw Garmin `.fit` files into a local SQLite hub
- tracks ingestion history and file-level outcomes
- serves a local dashboard for activities and ingestion status
- keeps archive files on disk and normalized activity data in the database

## Current Workflow

1. export `.fit` files from Garmin Connect
2. drop the raw files directly into `raw/garmin/inbox`
3. open the ingestion page in the local app
4. check the staging area
5. process the staging area
6. review the archive and database-backed UI

Inbox is intentionally a flat drop zone.

## Requirements

- Windows PowerShell
- Python available as `python`
- Node.js installed

## Install Dependencies

```powershell
$env:Path += ';C:\Program Files\nodejs'
& 'C:\Program Files\nodejs\npm.cmd' install
```

## Run The App

```powershell
$env:Path += ';C:\Program Files\nodejs'
& 'C:\Program Files\nodejs\npm.cmd' run dev -- --hostname 127.0.0.1 --port 3000
```

Open:

```text
http://127.0.0.1:3000
```

## Important Pages

- `/`
  activity dashboard
- `/activities`
  imported activities
- `/ingestion`
  staging area, preview, and processing

## Command-Line Helpers

### Preview Inbox

```powershell
python import_garmin_fit.py --fit-root raw/garmin/inbox --run-mode inbox --preview
```

### Process Inbox

```powershell
python import_garmin_fit.py --fit-root raw/garmin/inbox --run-mode inbox --archive-root raw/garmin/archive --failed-root raw/garmin/failed --athlete-name "D Hayashi" --timezone America/Chicago
```

## Test Cases

Stage inbox test scenarios:

```powershell
python scripts/stage_ingestion_test_cases.py --case all
```

Or one at a time:

```powershell
python scripts/stage_ingestion_test_cases.py --case wrong-folder-date
python scripts/stage_ingestion_test_cases.py --case duplicate-known
python scripts/stage_ingestion_test_cases.py --case mixed-day
```

## Repo Notes

- `data_hub.db`
  local SQLite database
- `raw/garmin/inbox`
  flat raw drop zone
- `raw/garmin/archive`
  archived FIT files after processing
- `raw/garmin/failed`
  files that could not be processed

## Continue Later

Read [Roadmap.md](c:\Users\dhayashi\move2Zero\Roadmap.md) in the next session
and continue from there.
