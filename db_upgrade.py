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
}


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


def upgrade(connection):
    added = add_missing_columns(connection)
    filled = fill_garmin_ids(connection)
    # One row per Garmin activity, enforced by the database. NULLs (files without an ID) are allowed.
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_garmin_activity_id
        ON activities(garmin_activity_id)
        WHERE garmin_activity_id IS NOT NULL
        """
    )
    connection.commit()
    return {"columns_added": added, "garmin_ids_filled": filled}


def apply_schema(connection, schema_path="schema.sql"):
    connection.executescript(Path(schema_path).read_text(encoding="utf-8"))
    return upgrade(connection)
