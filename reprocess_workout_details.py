#!/usr/bin/env python
"""Fill workout details for activities imported before they were captured. No downloads.

For every activity that has laps, re-read its archived FIT file and store, exactly as Garmin
recorded them: each lap's intensity, trigger and step index; the activity's workout name and
plan; and the planned workout steps. Laps are matched by number and start time, and an activity
whose FIT file does not line up with the database is skipped and reported, never forced.

    python reprocess_workout_details.py --dry-run   # report what would change, write nothing
    python reprocess_workout_details.py             # do it (safe to repeat)

Reversible: the new columns and table are additive, and a database backup should be taken first.
"""

import argparse
import fcntl
import os
import sqlite3
import sys
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

from db_upgrade import apply_schema  # noqa: E402
from fit_summary import canonicalize_fit  # noqa: E402
from import_garmin_fit import insert_workout_steps  # noqa: E402

DB_PATH = "data_hub.db"
LOCK_PATH = Path("temp/sync.lock")      # the same lock run_sync.py holds, so the two never overlap


def candidates(connection, redo):
    """Activities with laps. Unless --all, only those whose lap details have not been read yet."""
    has_marker = any(row[1] == "lap_details_at" for row in connection.execute("PRAGMA table_info(activities)"))
    condition = "" if (redo or not has_marker) else "AND a.lap_details_at IS NULL"
    return connection.execute(
        f"""
        SELECT a.id, a.garmin_activity_id, sf.file_path
        FROM activities a JOIN source_files sf ON sf.id = a.source_file_id
        WHERE EXISTS (SELECT 1 FROM laps l WHERE l.activity_id = a.id) {condition}
        ORDER BY a.id
        """
    ).fetchall()


def lines_up(db_laps, fit_laps):
    """True when the FIT laps are the same laps the database holds (count and start times)."""
    if len(db_laps) != len(fit_laps):
        return False
    return all(row[1] == lap["started_at_utc"] for row, lap in zip(db_laps, fit_laps))


def reprocess(connection, dry_run=False, redo=False, log=print):
    summary = {"activities": 0, "laps_updated": 0, "named_workouts": 0, "steps": 0, "skipped": []}
    rows = candidates(connection, redo)
    for number, (activity_id, garmin_id, file_path) in enumerate(rows, start=1):
        if not Path(file_path).exists():
            summary["skipped"].append((garmin_id, "FIT file not found"))
            continue
        try:
            canonical = canonicalize_fit(file_path)
        except Exception as problem:
            summary["skipped"].append((garmin_id, f"could not parse: {type(problem).__name__}"))
            continue
        db_laps = connection.execute(
            "SELECT lap_index, started_at_utc FROM laps WHERE activity_id = ? ORDER BY lap_index", (activity_id,)
        ).fetchall()
        if not lines_up(db_laps, canonical["laps"]):
            summary["skipped"].append((garmin_id, f"laps do not line up ({len(db_laps)} stored, {len(canonical['laps'])} in the file)"))
            continue
        summary["activities"] += 1
        summary["laps_updated"] += len(db_laps)
        activity = canonical["activity"]
        summary["named_workouts"] += bool(activity.get("workout_name"))
        summary["steps"] += len(canonical.get("workout_steps", []))
        if dry_run:
            continue
        connection.executemany(
            "UPDATE laps SET intensity = ?, lap_trigger = ?, wkt_step_index = ? WHERE activity_id = ? AND lap_index = ?",
            [(lap["intensity"], lap["lap_trigger"], lap["wkt_step_index"], activity_id, lap["lap_index"]) for lap in canonical["laps"]],
        )
        connection.execute(
            "UPDATE activities SET workout_name = ?, workout_description = ?, lap_details_at = CURRENT_TIMESTAMP WHERE id = ?",
            (activity.get("workout_name"), activity.get("workout_description"), activity_id),
        )
        connection.execute("DELETE FROM workout_steps WHERE activity_id = ?", (activity_id,))
        insert_workout_steps(connection, activity_id, canonical.get("workout_steps", []))
        if number % 50 == 0:
            connection.commit()
            log(f"{number}/{len(rows)} activities")
    if not dry_run:
        connection.commit()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Report what would change; write nothing.")
    parser.add_argument("--all", action="store_true", help="Redo activities that already have lap labels.")
    args = parser.parse_args()

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("A sync is running right now. Try again in a minute.")
        return 2

    connection = sqlite3.connect(args.db, timeout=30)
    connection.execute("PRAGMA foreign_keys = ON")
    if not args.dry_run:
        apply_schema(connection)       # adds the new columns and table if they are missing
    summary = reprocess(connection, dry_run=args.dry_run, redo=args.all)
    connection.close()

    verb = "would update" if args.dry_run else "updated"
    print(f"{verb} {summary['activities']} activities ({summary['laps_updated']} laps); "
          f"{summary['named_workouts']} have a Garmin workout name; {summary['steps']} planned steps.")
    if summary["skipped"]:
        print(f"skipped {len(summary['skipped'])}:")
        for garmin_id, reason in summary["skipped"][:15]:
            print(f"  {garmin_id}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
