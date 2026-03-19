-- Starter analytics layer for the SQLite data hub.
-- Apply these views to the database, then use the sample queries below.
--
-- Example:
--   python -c "import sqlite3; conn=sqlite3.connect('data_hub.db'); conn.executescript(open('analytics/starter_queries.sql', encoding='utf-8').read()); conn.close()"

DROP VIEW IF EXISTS vw_activity_overview;
CREATE VIEW vw_activity_overview AS
SELECT
    a.id AS activity_id,
    a.athlete_id,
    a.activity_type,
    a.sport,
    a.sub_sport,
    a.started_at_utc,
    a.timezone AS activity_timezone,
    date(a.started_at_utc) AS activity_date_utc,
    round(a.distance_m / 1609.344, 2) AS distance_miles,
    round(a.duration_seconds / 60.0, 2) AS duration_minutes,
    round((a.duration_seconds / 60.0) / NULLIF(a.distance_m / 1609.344, 0), 2) AS pace_min_per_mile,
    round(a.avg_speed_mps, 3) AS avg_speed_mps,
    round(a.avg_heart_rate_bpm, 1) AS avg_heart_rate_bpm,
    round(a.max_heart_rate_bpm, 1) AS max_heart_rate_bpm,
    round(a.avg_cadence_spm, 1) AS avg_cadence_spm,
    round(a.total_ascent_m * 3.28084, 1) AS total_ascent_ft,
    sf.file_name,
    sf.file_hash
FROM activities a
LEFT JOIN source_files sf ON sf.id = a.source_file_id;

DROP VIEW IF EXISTS vw_lap_overview;
CREATE VIEW vw_lap_overview AS
SELECT
    l.id AS lap_id,
    l.activity_id,
    l.lap_index,
    date(a.started_at_utc) AS activity_date_utc,
    round(l.distance_m / 1609.344, 2) AS lap_distance_miles,
    round(l.duration_seconds / 60.0, 2) AS lap_duration_minutes,
    round((l.duration_seconds / 60.0) / NULLIF(l.distance_m / 1609.344, 0), 2) AS lap_pace_min_per_mile,
    round(l.avg_speed_mps, 3) AS lap_avg_speed_mps,
    round(l.avg_heart_rate_bpm, 1) AS lap_avg_heart_rate_bpm,
    round(l.max_heart_rate_bpm, 1) AS lap_max_heart_rate_bpm,
    round(l.avg_cadence_spm, 1) AS lap_avg_cadence_spm
FROM laps l
JOIN activities a ON a.id = l.activity_id;

DROP VIEW IF EXISTS vw_weekly_activity_summary;
CREATE VIEW vw_weekly_activity_summary AS
SELECT
    athlete_id,
    strftime('%Y-W%W', started_at_utc) AS activity_week_utc,
    COUNT(*) AS activity_count,
    round(SUM(distance_m) / 1609.344, 2) AS total_miles,
    round(SUM(duration_seconds) / 60.0, 2) AS total_minutes,
    round(AVG(avg_heart_rate_bpm), 1) AS avg_activity_heart_rate_bpm,
    round(AVG(avg_cadence_spm), 1) AS avg_activity_cadence_spm
FROM activities
GROUP BY athlete_id, strftime('%Y-W%W', started_at_utc);

DROP VIEW IF EXISTS vw_activity_sample_rollup;
CREATE VIEW vw_activity_sample_rollup AS
SELECT
    s.activity_id,
    COUNT(*) AS sample_count,
    round(MIN(s.elapsed_seconds) / 60.0, 2) AS start_minute,
    round(MAX(s.elapsed_seconds) / 60.0, 2) AS end_minute,
    round(AVG(s.heart_rate_bpm), 1) AS avg_sample_heart_rate_bpm,
    round(MAX(s.heart_rate_bpm), 1) AS max_sample_heart_rate_bpm,
    round(AVG(s.cadence_spm), 1) AS avg_sample_cadence_spm,
    round(AVG(s.speed_mps), 3) AS avg_sample_speed_mps
FROM activity_samples s
GROUP BY s.activity_id;

DROP VIEW IF EXISTS vw_ingestion_latest_file_event;
CREATE VIEW vw_ingestion_latest_file_event AS
SELECT
    irf.file_hash,
    irf.source_file_id,
    irf.id AS ingestion_file_event_id,
    irf.ingestion_run_id,
    irf.file_path,
    irf.event_type,
    irf.message,
    irf.created_at
FROM ingestion_run_files irf
JOIN (
    SELECT
        file_hash,
        MAX(id) AS max_id
    FROM ingestion_run_files
    WHERE file_hash IS NOT NULL
    GROUP BY file_hash
) latest
    ON latest.file_hash = irf.file_hash
   AND latest.max_id = irf.id;

DROP VIEW IF EXISTS vw_source_file_current_state;
CREATE VIEW vw_source_file_current_state AS
SELECT
    sf.id AS source_file_id,
    sf.athlete_id,
    sf.file_name,
    sf.file_path,
    sf.file_hash,
    sf.file_size_bytes,
    sf.imported_at,
    sf.status AS source_status,
    sf.created_at,
    sf.updated_at,
    live.event_type AS latest_event_type,
    live.message AS latest_event_message,
    live.created_at AS latest_event_at,
    a.id AS activity_id,
    a.activity_type,
    a.sport,
    a.started_at_utc,
    a.timezone AS activity_timezone,
    date(a.started_at_utc) AS activity_date_utc
FROM source_files sf
LEFT JOIN vw_ingestion_latest_file_event live
    ON live.file_hash = sf.file_hash
LEFT JOIN activities a
    ON a.source_file_id = sf.id;

-- Sample queries

-- 1. Activity dashboard table
-- SELECT * FROM vw_activity_overview ORDER BY started_at_utc;

-- 2. Weekly mileage trend
-- SELECT * FROM vw_weekly_activity_summary ORDER BY activity_week_utc;

-- 3. Lap-by-lap splits
-- SELECT * FROM vw_lap_overview WHERE activity_id = 6 ORDER BY lap_index;

-- 4. Find hard-effort activities by average heart rate
-- SELECT *
-- FROM vw_activity_overview
-- WHERE avg_heart_rate_bpm >= 145
-- ORDER BY avg_heart_rate_bpm DESC;

-- 5. Compare sessions with pace vs heart rate
-- SELECT activity_id, activity_date_utc, distance_miles, pace_min_per_mile, avg_heart_rate_bpm
-- FROM vw_activity_overview
-- ORDER BY started_at_utc;

-- 6. Pull sample rollups for QC
-- SELECT *
-- FROM vw_activity_sample_rollup
-- ORDER BY activity_id;
