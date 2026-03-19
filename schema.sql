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

COMMIT;
