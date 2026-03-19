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

## Near-Term Follow-Ups

The next likely additions after the MVP are:

- `activity_metrics` for derived analytics
- `athlete_metrics` for threshold and profile values over time
- a dedicated `comments` table if annotations become more structured
- ingestion metadata tables if we build scheduled sync jobs
