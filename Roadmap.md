# Roadmap

## Current State

- SQLite-backed data hub is working.
- Garmin FIT import pipeline is working.
- Local Next.js app is working.
- Ingestion UI exists and can preview/process the Garmin inbox.
- Inbox currently acts as a flat staging area.
- Archive currently acts as the raw historical file reference.

## Important Clarification

When inbox looked "empty," that meant there were no `.fit` files left in it.
The date folders can still exist even if the inbox is operationally clear.

## Recently Completed

- Built canonical Garmin FIT import into `activities`, `laps`, and `activity_samples`
- Added ingestion run logging and file event logging
- Added Garmin inbox/archive/failed folder workflow
- Added ingestion preview flow
- Added interactive ingestion actions in the UI
- Simplified ingestion page language around a staging-area mental model
- Changed duplicate processing so already-imported files can be cleared from inbox
- Added repeatable ingestion test-case staging script
- Removed the special `_already_imported` archive bucket and folded those files back into the main archive structure
- Staged a wrong-folder-date inbox test case for UI validation
- Shifted inbox toward a flat drop-zone model instead of user-created date folders
- Changed ingestion page behavior so raw inbox files stay in a "needs check" staging state until a real preview report exists for the current inbox fingerprint
- Added preview snapshot caching so a successful staging check can drive detected dates and activity types on reload

## Active MVP Focus

Nail the ingestion experience before doing more visualization work.

### MVP goals for ingestion

- staging area should be easy to understand at a glance
- user should know what is ready to import
- user should know what failed and why
- user should know when an inbox date hint does not match detected activity date
- user should not need to pre-organize inbox files by date
- user should not need the terminal for normal import workflow

## Next Priority Work

1. Add clear warning badges in the ingestion UI.
   Goal:
   Date-hint mismatches and parse problems should stand out visually.

2. Add a dedicated "Problems" section on the ingestion page.
   Goal:
   Failed files and warning files should be separated from healthy files.

3. Make processing history more human-readable.
   Goal:
   Replace ledger-ish wording with plain-language summaries like:
   "Checked 4 files, imported 3, skipped 1 duplicate."

4. Add test-driven ingestion validation.
   Goal:
   Use staged inbox scenarios to verify:
   - wrong date hint
   - already imported duplicate
   - multiple activities on same day
   Current staged case:
   - wrong date hint in `raw/garmin/inbox/03-01-2026__22031296609_ACTIVITY.fit`

5. Decide whether brand-new inbox files should be parsed live on page load or only after an explicit staging check.
   Goal:
   Keep the UI fast for large inboxes without hiding useful metadata.

## Useful Commands

### Start the app

```powershell
$env:Path += ';C:\Program Files\nodejs'
& 'C:\Program Files\nodejs\npm.cmd' run dev -- --hostname 127.0.0.1 --port 3000
```

### Preview inbox

```powershell
python import_garmin_fit.py --fit-root raw/garmin/inbox --run-mode inbox --preview
```

### Process inbox

```powershell
python import_garmin_fit.py --fit-root raw/garmin/inbox --run-mode inbox --archive-root raw/garmin/archive --failed-root raw/garmin/failed --athlete-name "D Hayashi" --timezone America/Chicago
```

### Stage ingestion test cases

```powershell
python scripts/stage_ingestion_test_cases.py --case all
```

## Notes For Next Session

- Read this roadmap first.
- Stay focused on ingestion UX, not charts.
- Treat staging clarity as the top priority.
- Keep archive logic simple.
- Keep updating this file as work progresses.
