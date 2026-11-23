# move2Zero

A local training data hub. It pulls your activities and daily wellness from Garmin,
stores them in a SQLite database you own, and shows them on a local dashboard.

```text
Garmin Personal API  ->  raw FIT files + raw wellness JSON  ->  SQLite  ->  Next.js dashboard
```

Everything runs on your machine. Nothing is sent anywhere except the requests to Garmin.

## What You Get

- **Activities**: every run and workout, with laps and per-second samples (heart rate, pace, GPS)
- **Dashboard** (`/`): last-7-day KPIs, daily distance, pace per run, the latest outdoor run
  on a route map, and a Recovery section (sleep, resting heart rate, HRV, body battery)
- **Garmin Sync** (`/ingestion`): a sync button, the last result, key status, and history
- **Automatic sync**: every hour, at login, and when the Mac wakes. The dashboard warns when data is stale

## Requirements

- macOS
- Python 3 available as `python` (standard library only, nothing to install)
- Node.js (for the dashboard)
- A Garmin Personal API key (see below)

## Setup

1. Install the dashboard dependencies:

   ```bash
   npm install
   ```

2. Create a Garmin Personal API key in Garmin Connect, then put it in `.env`:

   ```text
   GARMIN_PERSONAL_API_KEY=your-key-here
   GARMIN_KEY_EXPIRES=2027-01-31
   ```

   `GARMIN_KEY_EXPIRES` is optional. Garmin does not report when a key expires, so copy the
   date from Garmin Connect to get a warning on the sync page and a notification before it
   runs out. `.env` is gitignored.

3. Run the first sync. It downloads your recent activities, imports them, and backfills
   30 days of wellness data:

   ```bash
   python run_sync.py
   ```

4. Start the dashboard:

   ```bash
   npm run dev -- --hostname 127.0.0.1 --port 3000
   ```

   Open http://127.0.0.1:3000

5. Turn on the automatic (hourly) sync:

   ```bash
   scripts/install_sync_schedule.sh
   ```

## Map Imagery

The latest outdoor run is drawn over satellite imagery. By default this is USGS The National Map
(US government imagery, public domain, no key; US coverage only). The dashboard's server fetches
each tile once and caches it in `temp/tiles`, so your browser never contacts the imagery provider.

What the provider can see: which map tiles were requested, which is roughly the area you run in
(for example around home), from this computer's IP address. Nothing else is sent.

Settings in `.env`, all optional:

```text
MAP_TILES=off                      # no imagery, the route is drawn on a plain background
MAP_TILE_URL=https://.../{z}/{x}/{y}.jpg   # any XYZ tile service (Esri, Mapbox, ...)
MAP_TILE_ATTRIBUTION=Imagery: Example  # shown on the map; match your provider's terms
```

Outside US coverage the default returns no imagery and the map falls back to the plain background.

## Daily Use

You should not need to do anything. The sync runs every hour and when the Mac wakes, and shows a
macOS notification only when something needs attention or new activities arrive.

To sync right now, press **Sync from Garmin now** on `/ingestion` or run `python run_sync.py`.

A sync missed while the Mac was asleep runs once when it wakes. If the last successful sync is
more than 3 hours old, the dashboard shows a stale-data banner.

## When Something Goes Wrong

- **Notification says the Garmin key was rejected or expired**: generate a new key in
  Garmin Connect, update `GARMIN_PERSONAL_API_KEY` (and `GARMIN_KEY_EXPIRES`) in `.env`,
  then press Sync.
- **A file landed in `raw/garmin/failed`**: it could not be parsed. The sync page lists it.
- **No FIT file from Garmin for an activity**: it is skipped and counted, not an error.
- **Importing a `.fit` file by hand**: drop it in `raw/garmin/inbox` and run a sync.
  This works even if the Garmin key has stopped working.

## Pages

- `/` dashboard
- `/activities` every imported activity
- `/activities/[id]` laps and detail for one activity
- `/ingestion` Garmin Sync status, button, and history
- `/api/activities`, `/api/summary`, `/api/ingestion` JSON endpoints

## Commands

```bash
python run_sync.py                       # fetch, import, archive, refresh wellness
python run_sync.py --json                # same, machine-readable (what the app uses)
python run_sync.py --skip-wellness       # activities only
python run_sync.py --since 2026-10-01 --full   # backfill activities from a date
python sync_garmin_api.py --dry-run      # see what would download, write nothing
python import_garmin_fit.py --fit-root some/folder   # import FIT files from anywhere

scripts/install_sync_schedule.sh --run-now     # trigger the scheduled job once
scripts/install_sync_schedule.sh --uninstall   # remove the scheduled job
```

Scheduled job output: `~/Library/Logs/move2zero-sync.log`.

## Layout

- `run_sync.py` one entry point for the button and the scheduled job
- `sync_garmin_api.py` downloads new activity FIT files
- `sync_garmin_wellness.py` downloads daily sleep, HRV, heart rate, and summary
- `import_garmin_fit.py`, `fit_summary.py` parse FIT files into the database
- `schema.sql` the database schema and migrations
- `app/`, `lib/` the Next.js dashboard
- `raw/garmin/inbox` files waiting to import, `archive` imported files, `failed` bad files
- `data_hub.db` the local database (gitignored)
- `docs/` design notes, including `garmin-personal-api-notes.md`
