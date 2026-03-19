# Data Hub Architecture Notes

## Goal

Build a centralized relational data hub where Garmin FIT data is only one source among many.

The system should let us:

- ingest data once from an external source
- store normalized data locally
- query our own database instead of repeatedly calling third-party endpoints
- support athlete views, coach views, and future analytics use cases
- make it easy to add more source plugins later without redesigning the core schema

For the MVP, we should optimize for one athlete first.

Right now that athlete is you, which is useful because it lets us validate the model on real data without prematurely designing for many users. The schema should still be multi-athlete capable, but the implementation can stay intentionally simple at the start.

## Design Principles

1. Source-specific ingestion should be separate from the core data model.
2. The core schema should describe the real-world entities, not Garmin's file format.
3. Raw source payloads should still be retained for auditability and reprocessing.
4. Derived metrics should be reproducible from stored raw or normalized data.
5. One athlete may have many activities; one activity may have many samples, laps, notes, and metrics.
6. The same core schema should support other future connectors, not just Garmin.

## Big Picture

Think in three layers:

1. Connector layer
   Garmin FIT parser, Garmin API sync, future Strava plugin, nutrition plugin, sleep plugin, coach notes plugin.

2. Canonical data layer
   The normalized relational schema that represents athletes, sessions, samples, metrics, and annotations.

3. Analytics layer
   SQL views, dashboards, reports, models, and visualizations built on top of the canonical layer.

Garmin should plug into layer 1 and write into layer 2.

## Recommended Storage Strategy

Start with SQLite for local development.

Why:

- simple and fast to stand up
- easy to inspect manually
- portable single-file database
- strong enough for a personal analytics hub
- easy to migrate later to Postgres if the project grows

Longer-term path:

- SQLite for local prototyping
- Postgres when multiple services, users, or heavier workloads appear

## Core Entity Model

These are the entities we should define early.

### athletes

Represents a person whose data we track.

Examples:

- yourself as an athlete
- a future coaching client
- test/demo users

Suggested fields:

- `id`
- `external_ref`
- `display_name`
- `birth_date` optional
- `sex` optional
- `height_cm` optional
- `weight_kg` optional
- `timezone`
- `created_at`
- `updated_at`

### data_sources

Represents where the data came from.

Examples:

- Garmin FIT file import
- Garmin API
- Strava API
- manual coach entry
- nutrition tracker

Suggested fields:

- `id`
- `source_type` such as `garmin_fit`, `garmin_api`, `manual`
- `source_name`
- `connector_version`
- `created_at`

### source_files

Stores the raw source artifact so imports are traceable and idempotent.

For Garmin FIT, this is the actual `.fit` file reference plus file metadata.

Suggested fields:

- `id`
- `data_source_id`
- `athlete_id` nullable at first if unknown
- `file_name`
- `file_path`
- `file_hash`
- `file_size_bytes`
- `imported_at`
- `raw_payload_location` optional
- `status`

This table helps us avoid duplicate imports and lets us reprocess files later.

### activities

Represents one workout, session, or event.

This should be a core table.

Suggested fields:

- `id`
- `athlete_id`
- `source_file_id`
- `source_activity_id` nullable for API-based imports
- `activity_type` such as `run`, `ride`, `walk`, `strength`
- `sport`
- `sub_sport` optional
- `started_at_utc`
- `ended_at_utc`
- `timezone`
- `duration_seconds`
- `moving_time_seconds` optional
- `distance_m`
- `calories_kcal` optional
- `total_ascent_m` optional
- `total_descent_m` optional
- `avg_speed_mps` optional
- `max_speed_mps` optional
- `avg_heart_rate_bpm` optional
- `max_heart_rate_bpm` optional
- `avg_cadence_spm` optional
- `max_cadence_spm` optional
- `training_load` optional
- `device_name` optional
- `created_at`
- `updated_at`

Relationships:

- one athlete has many activities
- one activity belongs to one athlete
- one source file may produce one or more activities depending on connector behavior

### laps

Represents splits or laps within an activity.

Suggested fields:

- `id`
- `activity_id`
- `lap_index`
- `started_at_utc` optional
- `ended_at_utc` optional
- `duration_seconds`
- `distance_m`
- `avg_speed_mps` optional
- `avg_heart_rate_bpm` optional
- `max_heart_rate_bpm` optional
- `avg_cadence_spm` optional
- `lap_type` optional

Relationships:

- one activity has many laps

This is a good starting shape and we will likely add more lap-level fields over time as we expand beyond the first Garmin import.

### activity_samples

Represents the time-series records from the FIT `record` messages.

This table is likely to become the largest table.

Suggested fields:

- `id`
- `activity_id`
- `sample_timestamp_utc`
- `elapsed_seconds` optional
- `distance_m` optional
- `speed_mps` optional
- `heart_rate_bpm` optional
- `cadence_spm` optional
- `power_watts` optional
- `altitude_m` optional
- `temperature_c` optional
- `latitude_semicircles` optional
- `longitude_semicircles` optional

Relationships:

- one activity has many samples

Notes:

- for performance, index `activity_id` and `sample_timestamp_utc`
- keep the schema broad enough for running, cycling, and other sports

Important boundary:

- comments about a workout should not live in `activity_samples`
- `activity_samples` should stay focused on time-series sensor data
- comments, athlete notes, and coach observations should live in `annotations` or a future dedicated comments table

Reason:

Workout comments describe the session as a whole or a meaningful event within it, not each sensor sample. If we later ingest comments from Garmin, Strava, or a coaching app, they should map into a session-level note or comment model rather than being mixed into per-second sample data.

### activity_metrics

Stores derived metrics at the activity level.

This is different from the raw imported fields in `activities`. These are computed metrics.

Examples:

- time in zone percentages
- pace drift
- efficiency factor
- workload score
- normalized power
- VO2-oriented estimates

Suggested fields:

- `id`
- `activity_id`
- `metric_name`
- `metric_value`
- `metric_unit`
- `calculated_at`
- `calculation_version`

This gives flexibility without changing the core schema every time we invent a new metric.

### athlete_metrics

Stores point-in-time athlete-level metrics that may change over time.

Examples:

- resting heart rate
- lactate threshold heart rate
- max heart rate
- body weight
- threshold pace
- FTP

Suggested fields:

- `id`
- `athlete_id`
- `metric_name`
- `metric_value`
- `metric_unit`
- `effective_at`
- `source`

This is important because zones and threshold logic change over time.

### annotations

Stores manual notes and coach observations tied to activities or athletes.

Examples:

- RPE
- felt heavy
- hamstring tightness
- under-fueled
- windy conditions
- coach feedback
- workout comments

Suggested fields:

- `id`
- `athlete_id`
- `activity_id` nullable
- `annotation_type`
- `value_text`
- `value_numeric` optional
- `created_at`
- `created_by`

This is where we connect objective and subjective training data.

For the MVP, `annotations` can also serve as the home for workout comments. If comments become more structured later, we can split them into a dedicated `comments` table without breaking the rest of the model.

### injuries_or_flags

Optional early table, but likely valuable if coaching use cases matter.

Examples:

- left hamstring tightness
- shin pain
- calf strain risk
- fatigue flag

Suggested fields:

- `id`
- `athlete_id`
- `activity_id` nullable
- `body_region`
- `severity`
- `description`
- `status`
- `reported_at`
- `resolved_at` optional

## Relationship Summary

At a high level:

- one `athlete` has many `activities`
- one `activity` has many `laps`
- one `activity` has many `activity_samples`
- one `activity` has many `activity_metrics`
- one `athlete` has many `athlete_metrics`
- one `athlete` has many `annotations`
- one `activity` may have many `annotations`
- one `data_source` has many `source_files`
- one `source_file` may map to one or more `activities`

## Why This Shape Works

This design separates:

- source provenance
- normalized session data
- high-volume time-series data
- subjective notes
- computed metrics

That separation matters because future plugins will not all look like Garmin FIT files.

Examples:

- a nutrition plugin might create meal records and nutrition metrics
- a sleep plugin might create sleep sessions and recovery metrics
- a coaching notes plugin might create annotations without any device samples
- an API connector might have a source activity id but no local file

The canonical model should survive those differences.

## What Should Be Garmin-Specific

Garmin-specific logic should live in the connector/import layer, not the central schema.

Examples of Garmin-specific concerns:

- FIT message numbers
- FIT field ids like `3`, `4`, `8`, `9`, `253`
- Garmin naming quirks
- Garmin-only fields that may not exist elsewhere

The parser can map those fields into canonical names before insert.

## What Should Be Canonical

The central hub should speak in general concepts:

- athlete
- activity
- lap
- sample
- metric
- annotation
- source

That lets us plug in new systems without redesigning the database every time.

## Raw vs Normalized Data

We should keep both.

Recommended approach:

- store file metadata and file hash in `source_files`
- optionally preserve raw parsed records in a raw staging table or JSON column later
- also store normalized rows in the canonical tables

Why:

- easier debugging
- easier reprocessing when parser logic improves
- lets us compare old and new ingestion logic

## Import Pipeline Proposal

For Garmin FIT imports:

1. discover `.fit` files
2. calculate file hash
3. skip already imported files
4. parse file into source messages
5. map messages into canonical objects
6. insert into `activities`, `laps`, `activity_samples`, and optional metrics
7. store import status and timestamps

Future automation path:

Today the process may be manual file download plus import. Later, we can automate acquisition in a separate sync layer without changing the core relational model.

Examples:

- Garmin API synchronization if access is available
- automated browser or export workflow if allowed and reliable
- polling a watched folder where new FIT files are dropped
- a connector service that downloads source files on a schedule

The key idea is that file acquisition is separate from normalization and storage. That means we can improve automation later without rewriting the hub schema.

## Initial MVP Scope

To avoid overbuilding, first implementation should only require:

- `athletes`
- `data_sources`
- `source_files`
- `activities`
- `laps`
- `activity_samples`
- `annotations`

That is enough to:

- import workouts
- query local history
- build charts
- compare sessions
- add manual coaching notes

For the first pass, we should also assume:

- one primary athlete
- Garmin FIT file import as the only active connector
- manual import is acceptable while ingestion and schema stabilize
- future integrations such as Strava should influence the design, but not complicate the MVP implementation

We can add `activity_metrics` and `athlete_metrics` once the ingestion is stable.

## Example Questions This Schema Can Answer

Athlete-style questions:

- what was my average heart rate for each run this month?
- how much did I run this week?
- what did my pace look like on tempo days?
- when did my cadence trend upward?

Coach-style questions:

- how many high-intensity sessions did this athlete do in the last 14 days?
- which workouts showed strong pace but unusually high heart rate?
- is the athlete trending toward fatigue based on subjective notes plus HR drift?
- what sessions were flagged with hamstring pain?

System-style questions:

- which source files have already been imported?
- which connector version produced these rows?
- which files failed parsing and need reprocessing?

## Recommended Next Decisions

Before coding the database, we should lock in:

1. whether the central hub is athlete-centric only, or broader for many wellness domains
2. whether we want flexible metric tables early, or only strongly typed session tables first
3. whether source raw data should be stored only as file references or also as parsed JSON snapshots
4. whether we want one database for everything, or a hub database plus connector staging areas

These are still worth keeping in view, but we do not need to resolve every one of them before the first Garmin-backed version is live. This becomes more important once we add the next integration, which will likely be Strava.

## My Recommendation

For this repo, I recommend:

- start with SQLite
- define a canonical activity schema now
- keep Garmin-specific parsing logic isolated
- store source file metadata and hashes for idempotent imports
- add annotations early so subjective coach-style notes are first-class data
- postpone highly generic plugin abstractions until after Garmin import is working

That gives us a clean foundation without trying to solve every future plugin on day one.

## Practical Next Step

After we agree on this shape, the next implementation milestone should be:

1. create a SQLite schema file
2. refactor the current FIT parser to return structured canonical objects
3. build an importer that loads all existing Garmin FIT files into the database
4. add a few starter SQL queries or views for common analysis
