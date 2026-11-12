# Garmin Personal API Notes

## Status

Verified live against the real account on 2026-11-12:

- token exchange works
- activity list works
- original FIT download works (arrives as a zip)
- the existing importer previews an API-sourced FIT with no warnings or errors
- all four wellness endpoints tried returned `200`

Built: `sync_garmin_api.py`, `run_sync.py`, the sync page, and the nightly job. Not yet built: key expiry warning in the UI and wellness ingestion.

## Sync Flow

`run_sync.py` is the single entry point. The Sync button and the nightly job both call it, so they behave identically.

```bash
python run_sync.py                 # human-readable
python run_sync.py --json          # what the app route parses
python run_sync.py --trigger nightly --notify
```

What one run does:

1. fetch new activity FIT files from Garmin into `raw/garmin/inbox` (`sync_garmin_api.py`)
2. import everything in the inbox with `import_garmin_fit.py`, archive successes, move failures to `raw/garmin/failed`
3. write `temp/last_sync.json` (what the Garmin Sync page shows) and print a one-line summary

Details worth remembering:

- a failed Garmin step does not stop the import, so a `.fit` dropped into the inbox by hand still gets imported when the key has expired
- a lock file (`temp/sync.lock`) stops the button and the nightly job from running at the same time
- athlete name and timezone live at the top of `run_sync.py`, not in the JS route
- `--notify` raises a macOS notification on failure, so an expired key is not silent

## Sync Button

- lives on `/ingestion` ("Sync from Garmin now")
- `POST /api/ingestion` with `{ "action": "sync" }` runs `run_sync.py --json` with a 20 minute timeout
- success reloads the page and the result shows in the "Last sync" card; errors stay on screen
- the old Check Staging Area / Process Staging Area actions, preview cache, and date-hint logic were removed

## Nightly Sync

```bash
scripts/install_nightly_sync.sh              # every night at 00:00
scripts/install_nightly_sync.sh --run-now    # trigger one run now
scripts/install_nightly_sync.sh --uninstall
```

- installs a launchd agent at `~/Library/LaunchAgents/com.move2zero.nightly-sync.plist`, generated with this machine's paths
- launchd runs a missed job when the Mac wakes, so a sleeping laptop at midnight still syncs
- output goes to `~/Library/Logs/move2zero-sync.log`
- the Garmin Sync page shows whether the agent is installed and the result of the last run
- verified 2026-11-12 by triggering it through launchd (`trigger: nightly`, `ok: true`)
- the key still expires eventually (30 days to a year, unconfirmed). When it does the nightly run fails with a notification and the page shows "Needs attention". Generate a new key in Garmin Connect and update `.env`.

## What The Personal Tier Is

Garmin reopened the Connect Developer Program in October 2026 with a self-serve Personal tier.

- for an individual's own Garmin Connect data
- key is generated in Garmin Connect, no application step
- pull only, nothing is pushed to us
- covers activity data (JSON and original FIT), health data, women's health data
- Courses and Training APIs are business-tier only

Sources for the above and the remaining unknowns are marked below. Garmin's official page does not state pricing or numeric rate limits.

## Official Versus Reported

Confirmed on Garmin's own overview page:

- Personal tier eligibility, pull-only, and the data categories

Learned from the open-source reference clients (`tomrichmond/garmin-personal-api`, `philippfromme/garmin-download`) and then confirmed by our own calls:

- all endpoint paths in this file
- no refresh tokens, new token each time

Reported by third parties and not verified by us:

- key expiry between 30 days and a year
- rate limits (Garmin does not publish a number, so assume they exist)
- whether Garmin strips some proprietary fields from API FIT files compared with device-uploaded ones

## Credentials

- `GARMIN_PERSONAL_API_KEY` lives in `.env` (already gitignored via `.env` and `.env.*`)
- the key is the long-lived secret, the access token is the short-lived one
- never print, log, or paste either one
- if either leaks into git history or a chat, regenerate the key in Garmin Connect

## Auth Flow

Base URL: `https://personal.connectapi.garmin.com`

1. exchange the key for a token

```text
POST /personalapitoken-service/personal-api/personal-api-key/token
Authorization: ApiKey <key>
```

2. call data endpoints with the token

```text
Authorization: Bearer <token>
```

Token facts observed:

- response is plain text, not JSON
- it is a JWT, valid for 24 hours (`exp` minus `iat` is 86400 seconds)
- scopes include fitness, nutrition, user, and wellness reads
- there is no refresh token, so the connector requests a new one

Connector rule: fetch a fresh token when none is held, when it is older than about 23 hours, and once on any `401`.

## Endpoints Verified

All use `Authorization: Bearer <token>`.

### Activity list

```text
GET /activitylist-service/activities/search/activities?start=0&limit=20
Accept: application/json
```

- returns a JSON array, newest first
- `start` is a zero-based offset, `limit` is page size
- reference client uses a page size of 20 and stops when a page comes back short
- each item carries `activityId`, `activityName`, `startTimeLocal`, `startTimeGMT`, `distance`, `duration`, `activityType`, plus heart rate, cadence, training effect, and HR-zone time fields
- `startTimeLocal` is `YYYY-MM-DD HH:MM:SS`

### Original FIT download

```text
GET /download-service/files/activity/{activityId}
Accept: */*
```

- returns a **zip**, content type `application/x-zip-compressed`
- the zip holds one file named `<activityId>_ACTIVITY.fit`, which matches our manual export naming
- `404` or `204` means no original file exists for that activity, so skip it

Gotcha: `Accept: application/json` returns `406 NotAcceptableException`. Using only `application/zip, application/octet-stream` also returned `406` in our first attempt. Send `*/*` or include `application/x-zip-compressed`.

### Wellness (all `GET`, all returned `200`)

```text
/usersummary-service/usersummary/daily?calendarDate=YYYY-MM-DD
/sleep-service/sleep/dailySleep?date=YYYY-MM-DD
/hrv-service/hrv/YYYY-MM-DD
/wellness-service/wellness/dailyHeartRate?date=YYYY-MM-DD
```

The reference client also uses `/wellness-service/wellness/daily/spo2acclimation/YYYY-MM-DD` for pulse ox. We have not called it yet.

Response shapes for wellness are not yet inspected. Do that before designing tables.

## How It Fits The Existing Pipeline

The importer needs no change for activities.

- the API FIT file previewed cleanly through `import_garmin_fit.py --preview` (running activity, one session, correct detected date)
- the connector should only fetch, unzip, and write `<activityId>_ACTIVITY.fit` into `raw/garmin/inbox`
- everything after that is the existing flow: staging check, process, archive, `source_files` idempotency

This matches the layering in `data-hub-architecture.md`: the API is a second connector feeding the same canonical tables.

## Connector Design Rules

- fetch the list newest first and stop paging once we hit activities already recorded, so a normal sync is one request
- skip an activity if its file already exists in inbox or archive, or its id is already known in the database
- write files atomically (temp file, then rename) so the importer never sees a partial FIT
- pause between downloads (the reference client waits 1.5 seconds)
- retry on `429` and `5xx` with backoff, honor `Retry-After` when present
- treat `404` and `204` on download as "no original file", not an error
- fail clearly when the key is missing, rejected, or expired, and surface that in the UI instead of silently syncing nothing

## Open Questions

- exact key expiry for our key, and how to show days remaining in the UI
- Garmin's real rate limit
- whether API FIT files differ from manual exports in any field we use (compare one activity both ways)
- whether the API exposes older history in bulk, and how far back
- wellness response shapes and which of them earn their own tables
- whether the Personal terms allow anything beyond reading our own data into a local store (we are well inside "own data, own use")

## Suggested Build Order

1. a sync script that pulls new activity FIT files into inbox
2. a "Sync from Garmin" action on the ingestion page that runs it
3. key and token status in the UI, including expiry warnings
4. wellness ingestion: inspect response shapes, then add tables to `schema.sql`
5. revisit the roadmap, since automatic arrival reduces the need for manual staging polish

## Data Quality Notes (found while building the dashboard)

- `activity_samples.latitude_semicircles` and `longitude_semicircles` contain the FIT invalid sentinel `2147483647` ("no GPS fix yet") on the first few samples of outdoor runs. Converted to degrees it is exactly 180, so it ruins any bounding box or distance calculation.
- the importer currently stores these as real values. Any GPS query must filter them out: latitude between `-1073741824` and `1073741824`, longitude between `-2147483647` and `2147483646`. `lib/data.js` does this in `VALID_FIX_SQL`.
- the cleaner long-term fix is to store `NULL` for invalid fixes in `import_garmin_fit.py` (or `fit_summary.py`). Not done yet because it changes stored data and would need a re-import.
- treadmill runs have no GPS and no altitude, so they are excluded from the route panel
- altitude is also empty on the outdoor runs imported so far, so there is no elevation profile yet
- long stops (the timer keeps running) show up as sharp slow spikes in the pace profile, which is accurate; the axis clamps them so they do not flatten the rest of the line
