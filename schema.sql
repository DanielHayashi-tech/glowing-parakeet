PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS athletes (
    id INTEGER PRIMARY KEY,
    external_ref TEXT,
    display_name TEXT NOT NULL,
    birth_date TEXT,
    sex TEXT,
    height_cm REAL,
    weight_kg REAL,
    timezone TEXT NOT NULL DEFAULT 'America/Chicago',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_sources (
    id INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    connector_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, source_name)
);

CREATE TABLE IF NOT EXISTS source_files (
    id INTEGER PRIMARY KEY,
    data_source_id INTEGER NOT NULL,
    athlete_id INTEGER,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    file_size_bytes INTEGER,
    imported_at TEXT,
    raw_payload_location TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (data_source_id) REFERENCES data_sources(id),
    FOREIGN KEY (athlete_id) REFERENCES athletes(id),
    UNIQUE(file_hash),
    UNIQUE(file_path)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL,
    run_mode TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    scanned_file_count INTEGER NOT NULL DEFAULT 0,
    imported_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS ingestion_run_files (
    id INTEGER PRIMARY KEY,
    ingestion_run_id INTEGER NOT NULL,
    source_file_id INTEGER,
    file_path TEXT NOT NULL,
    file_hash TEXT,
    event_type TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ingestion_run_id) REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (source_file_id) REFERENCES source_files(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    athlete_id INTEGER NOT NULL,
    source_file_id INTEGER,
    source_activity_id TEXT,
    activity_type TEXT NOT NULL,
    sport TEXT,
    sub_sport TEXT,
    started_at_utc TEXT,
    ended_at_utc TEXT,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    duration_seconds REAL,
    moving_time_seconds REAL,
    distance_m REAL,
    calories_kcal REAL,
    total_ascent_m REAL,
    total_descent_m REAL,
    avg_speed_mps REAL,
    max_speed_mps REAL,
    avg_heart_rate_bpm REAL,
    max_heart_rate_bpm REAL,
    avg_cadence_spm REAL,
    max_cadence_spm REAL,
    training_load REAL,
    device_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    garmin_activity_id INTEGER,
    start_time_local TEXT,
    local_date TEXT,
    utc_offset_minutes INTEGER,
    utc_offset_source TEXT,
    activity_name TEXT,
    garmin_type_key TEXT,
    aerobic_training_effect REAL,
    anaerobic_training_effect REAL,
    training_effect_label TEXT,
    hr_zone1_seconds REAL,
    hr_zone2_seconds REAL,
    hr_zone3_seconds REAL,
    hr_zone4_seconds REAL,
    hr_zone5_seconds REAL,
    metrics_fetched_at TEXT,
    lap_distance_sum_m REAL,
    lap_distance_adjusted INTEGER,
    fit_distance_m REAL,
    fit_duration_seconds REAL,
    garmin_adjusted INTEGER,
    FOREIGN KEY (athlete_id) REFERENCES athletes(id),
    FOREIGN KEY (source_file_id) REFERENCES source_files(id)
);

CREATE TABLE IF NOT EXISTS laps (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL,
    lap_index INTEGER NOT NULL,
    started_at_utc TEXT,
    ended_at_utc TEXT,
    duration_seconds REAL,
    distance_m REAL,
    avg_speed_mps REAL,
    max_speed_mps REAL,
    avg_heart_rate_bpm REAL,
    max_heart_rate_bpm REAL,
    avg_cadence_spm REAL,
    lap_type TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
    UNIQUE(activity_id, lap_index)
);

CREATE TABLE IF NOT EXISTS activity_samples (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL,
    sample_timestamp_utc TEXT,
    elapsed_seconds REAL,
    distance_m REAL,
    speed_mps REAL,
    heart_rate_bpm REAL,
    cadence_spm REAL,
    power_watts REAL,
    altitude_m REAL,
    temperature_c REAL,
    latitude_semicircles INTEGER,
    longitude_semicircles INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY,
    athlete_id INTEGER NOT NULL,
    activity_id INTEGER,
    annotation_type TEXT NOT NULL,
    value_text TEXT,
    value_numeric REAL,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (athlete_id) REFERENCES athletes(id),
    FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_source_files_data_source_id
    ON source_files(data_source_id);

CREATE INDEX IF NOT EXISTS idx_source_files_athlete_id
    ON source_files(athlete_id);

CREATE INDEX IF NOT EXISTS idx_source_files_status
    ON source_files(status);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source_type
    ON ingestion_runs(source_type);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started_at
    ON ingestion_runs(started_at);

CREATE INDEX IF NOT EXISTS idx_ingestion_run_files_run_id
    ON ingestion_run_files(ingestion_run_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_run_files_source_file_id
    ON ingestion_run_files(source_file_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_run_files_event_type
    ON ingestion_run_files(event_type);

CREATE INDEX IF NOT EXISTS idx_activities_athlete_id
    ON activities(athlete_id);

CREATE INDEX IF NOT EXISTS idx_activities_source_file_id
    ON activities(source_file_id);

CREATE INDEX IF NOT EXISTS idx_activities_started_at_utc
    ON activities(started_at_utc);

CREATE INDEX IF NOT EXISTS idx_laps_activity_id
    ON laps(activity_id);

CREATE INDEX IF NOT EXISTS idx_activity_samples_activity_id
    ON activity_samples(activity_id);

CREATE INDEX IF NOT EXISTS idx_activity_samples_timestamp
    ON activity_samples(sample_timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_activity_samples_activity_timestamp
    ON activity_samples(activity_id, sample_timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_annotations_athlete_id
    ON annotations(athlete_id);

CREATE INDEX IF NOT EXISTS idx_annotations_activity_id
    ON annotations(activity_id);

CREATE INDEX IF NOT EXISTS idx_annotations_type
    ON annotations(annotation_type);

INSERT OR IGNORE INTO schema_migrations(version)
VALUES ('0001_initial_schema');

INSERT OR IGNORE INTO schema_migrations(version)
VALUES ('0002_ingestion_runs');

-- 0003: earlier imports stored FIT's "no GPS fix" marker (0x7FFFFFFF = 180 degrees).
-- Null those out once; the importer no longer stores them.
UPDATE activity_samples
SET latitude_semicircles = NULL, longitude_semicircles = NULL
WHERE NOT EXISTS (
        SELECT 1 FROM schema_migrations WHERE version = '0003_null_invalid_gps'
    )
    AND (
        latitude_semicircles NOT BETWEEN -1073741824 AND 1073741824
        OR longitude_semicircles = 2147483647
    );

INSERT OR IGNORE INTO schema_migrations(version)
VALUES ('0003_null_invalid_gps');

-- 0004: daily wellness (sleep, HRV, heart rate, body battery) from the Garmin Personal API.
-- wellness_raw keeps Garmin's responses so more fields can be extracted later without refetching.
CREATE TABLE IF NOT EXISTS wellness_daily (
    athlete_id INTEGER NOT NULL,
    calendar_date TEXT NOT NULL,
    steps INTEGER,
    step_goal INTEGER,
    active_kcal REAL,
    moderate_intensity_minutes INTEGER,
    vigorous_intensity_minutes INTEGER,
    resting_hr_bpm INTEGER,
    resting_hr_7d_avg_bpm INTEGER,
    min_hr_bpm INTEGER,
    max_hr_bpm INTEGER,
    avg_stress INTEGER,
    body_battery_high INTEGER,
    body_battery_low INTEGER,
    body_battery_at_wake INTEGER,
    sleep_seconds INTEGER,
    deep_sleep_seconds INTEGER,
    light_sleep_seconds INTEGER,
    rem_sleep_seconds INTEGER,
    awake_seconds INTEGER,
    sleep_score INTEGER,
    sleep_avg_hr_bpm REAL,
    sleep_avg_spo2 REAL,
    sleep_avg_respiration REAL,
    sleep_start_utc TEXT,
    sleep_end_utc TEXT,
    hrv_last_night_avg INTEGER,
    hrv_weekly_avg INTEGER,
    hrv_status TEXT,
    hrv_balanced_low INTEGER,
    hrv_balanced_upper INTEGER,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (athlete_id, calendar_date),
    FOREIGN KEY (athlete_id) REFERENCES athletes(id)
);

CREATE TABLE IF NOT EXISTS wellness_raw (
    athlete_id INTEGER NOT NULL,
    calendar_date TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (athlete_id, calendar_date, kind),
    FOREIGN KEY (athlete_id) REFERENCES athletes(id)
);

INSERT OR IGNORE INTO schema_migrations(version)
VALUES ('0004_wellness');

-- 0005: Garmin IDs, local time, and Garmin's own training metrics.
-- New activity columns and the unique Garmin-ID index are added by db_upgrade.py (SQLite cannot
-- ADD COLUMN IF NOT EXISTS). garmin_activity_raw keeps Garmin's original list JSON per activity so
-- fields can be re-extracted without asking Garmin again. fit_status explains any activity with no
-- imported FIT: pending, imported, no_original (Garmin has no file for it), or invalid.
CREATE TABLE IF NOT EXISTS garmin_activity_raw (
    garmin_activity_id INTEGER PRIMARY KEY,
    payload TEXT NOT NULL,
    fit_status TEXT NOT NULL DEFAULT 'pending',
    fit_status_detail TEXT,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status_updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One row per day we asked Garmin for wellness data, so "no data" is recorded, not guessed.
CREATE TABLE IF NOT EXISTS wellness_fetch_log (
    athlete_id INTEGER NOT NULL,
    calendar_date TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (athlete_id, calendar_date),
    FOREIGN KEY (athlete_id) REFERENCES athletes(id)
);

INSERT OR IGNORE INTO schema_migrations(version)
VALUES ('0005_garmin_ids_local_time_metrics');

COMMIT;
