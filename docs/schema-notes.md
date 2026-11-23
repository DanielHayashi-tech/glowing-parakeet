# Schema Notes

## MVP Scope

The first schema intentionally stays small:

- `athletes`
- `data_sources`
- `source_files`
- `activities`
- `laps`
- `activity_samples`
- `annotations`

This is enough to support Garmin FIT import, local querying, workout notes, and visualization work without locking us into Garmin-specific assumptions.

## Why SQLite First

SQLite is the right starting point for this repo because:

- we have one primary athlete right now
- we want fast iteration on the data model
- we do not need service infrastructure yet
- the schema can be migrated to Postgres later if the hub grows

## A Few Important Choices

### `source_files` exists for idempotency

We want to ingest each FIT file once and keep a durable reference to where it came from.

That table is responsible for:

- file path tracking
- file hash deduplication
- import status
- future reprocessing

### `activity_samples` stays sensor-focused

This table is only for time-series measurements such as timestamped heart rate, speed, cadence, altitude, and position.

Workout comments do not belong here.

### `annotations` holds comments and notes

For the MVP, `annotations` is the home for:

- workout comments
- RPE
- subjective feel
- weather notes
- pain or injury notes
- coach observations

If comments later need threading, authorship rules, or replies, we can split out a dedicated `comments` table.

## Wellness Tables (migration 0004)

Daily wellness is not an activity, so it has its own tables:

- `wellness_daily` has one row per athlete per day: steps, resting and min/max heart rate, stress, body battery, sleep duration and stages, sleep score, overnight HRV and Garmin's balanced range.
- `wellness_raw` keeps Garmin's original JSON per day and kind (summary, sleep, hrv, heart_rate). It is the same idea as keeping the raw FIT file: more fields can be extracted later without calling the API again.

Re-fetching a day updates both tables in place, because today's numbers keep changing and last night's sleep lands in the morning.

## Activity Identity And Garmin Values (migration 0005)

- `garmin_activity_id` is Garmin's own ID, unique in the database.
- `local_date`, `start_time_local`, `utc_offset_minutes` come from the activity's own offset, so use `local_date` for any "which day" or "which week" question.
- `distance_m` and `duration_seconds` follow Garmin's servers; `fit_distance_m` and `fit_duration_seconds` keep the FIT's own values and `garmin_adjusted` marks a difference.
- `aerobic_training_effect`, `anaerobic_training_effect`, `training_load`, `hr_zone1..5_seconds` come from Garmin's activity list.
- `garmin_activity_raw` keeps the original list JSON and a `fit_status` (pending, imported, no_original, invalid) for every Garmin activity.
- `wellness_fetch_log` records each wellness day as ok, empty, or error.

## Migrations

`schema.sql` is idempotent and runs on every import and wellness sync. Structure uses `CREATE TABLE IF NOT EXISTS`. One-off data fixes guard themselves with a `schema_migrations` check so they run once:

- `0003_null_invalid_gps` nulled the FIT "no GPS fix" sentinel (180 degrees) that early imports stored as a real coordinate. The importer now stores `NULL`.

## Near-Term Follow-Ups

The next likely additions after the MVP are:

- `activity_metrics` for derived analytics
- `athlete_metrics` for threshold and profile values over time
- a dedicated `comments` table if annotations become more structured
- more wellness fields (stress, body battery through the day) promoted out of `wellness_raw`
