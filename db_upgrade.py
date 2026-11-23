"""Schema upgrades that plain `CREATE TABLE IF NOT EXISTS` cannot do on an existing database.

schema.sql is idempotent for new tables, but SQLite has no `ADD COLUMN IF NOT EXISTS`.
apply_schema() runs schema.sql, then adds any missing columns, the unique Garmin-ID
index, and fills Garmin IDs for rows imported before the column existed.
"""

import re
import sqlite3
from pathlib import Path

ACTIVITY_COLUMNS = {
    "garmin_activity_id": "INTEGER",
    "start_time_local": "TEXT",
    "local_date": "TEXT",
    "utc_offset_minutes": "INTEGER",
    "utc_offset_source": "TEXT",
    "activity_name": "TEXT",
    "garmin_type_key": "TEXT",
    "aerobic_training_effect": "REAL",
    "anaerobic_training_effect": "REAL",
    "training_effect_label": "TEXT",
    "hr_zone1_seconds": "REAL",
    "hr_zone2_seconds": "REAL",
    "hr_zone3_seconds": "REAL",
    "hr_zone4_seconds": "REAL",
    "hr_zone5_seconds": "REAL",
    "metrics_fetched_at": "TEXT",
    # Treadmill distance calibration: laps and records keep the device's raw distance while the
    # session distance (what Garmin Connect shows) is the adjusted one. We keep both and flag it.
    "lap_distance_sum_m": "REAL",
    "lap_distance_adjusted": "INTEGER",
}

LAP_MISMATCH_TOLERANCE = 0.01  # 1%
LAP_MISMATCH_MIN_METERS = 25


def existing_columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def add_missing_columns(connection):
    present = existing_columns(connection, "activities")
    added = []
    for name, sql_type in ACTIVITY_COLUMNS.items():
        if name not in present:
            connection.execute(f"ALTER TABLE activities ADD COLUMN {name} {sql_type}")
            added.append(name)
    return added


def fill_garmin_ids(connection):
    """Rows imported earlier only carry the Garmin ID in the source file name (<id>_ACTIVITY.fit)."""
    rows = connection.execute(
        """
        SELECT a.id, sf.file_name
        FROM activities a
        JOIN source_files sf ON sf.id = a.source_file_id
        WHERE a.garmin_activity_id IS NULL
        """
    ).fetchall()
    filled = 0
    for activity_id, file_name in rows:
        match = re.match(r"(\d+)_ACTIVITY", file_name or "")
        if match:
            connection.execute(
                "UPDATE activities SET garmin_activity_id = ?, source_activity_id = COALESCE(source_activity_id, ?) WHERE id = ?",
                (int(match.group(1)), match.group(1), activity_id),
            )
            filled += 1
    return filled


def update_lap_check(connection, activity_id):
    """Record sum(lap distance) and whether it disagrees with the session distance by more than 1%."""
    row = connection.execute(
        """
        SELECT a.distance_m, (SELECT SUM(distance_m) FROM laps WHERE activity_id = a.id)
        FROM activities a WHERE a.id = ?
        """,
        (activity_id,),
    ).fetchone()
    if not row or row[1] is None:
        return
    session_distance, lap_sum = row
    adjusted = 0
    if session_distance and abs(lap_sum - session_distance) > max(
        LAP_MISMATCH_MIN_METERS, LAP_MISMATCH_TOLERANCE * session_distance
    ):
        adjusted = 1
    connection.execute(
        "UPDATE activities SET lap_distance_sum_m = ?, lap_distance_adjusted = ? WHERE id = ?",
        (lap_sum, adjusted, activity_id),
    )


def fill_lap_checks(connection):
    ids = [
        row[0]
        for row in connection.execute(
            "SELECT id FROM activities WHERE lap_distance_sum_m IS NULL AND EXISTS (SELECT 1 FROM laps WHERE activity_id = activities.id)"
        )
    ]
    for activity_id in ids:
        update_lap_check(connection, activity_id)
    return len(ids)


def upgrade(connection):
    added = add_missing_columns(connection)
    filled = fill_garmin_ids(connection)
    lap_checks = fill_lap_checks(connection)
    # One row per Garmin activity, enforced by the database. NULLs (files without an ID) are allowed.
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_garmin_activity_id
        ON activities(garmin_activity_id)
        WHERE garmin_activity_id IS NOT NULL
        """
    )
    connection.commit()
    return {"columns_added": added, "garmin_ids_filled": filled, "lap_checks_filled": lap_checks}


def apply_schema(connection, schema_path="schema.sql"):
    connection.executescript(Path(schema_path).read_text(encoding="utf-8"))
    return upgrade(connection)
