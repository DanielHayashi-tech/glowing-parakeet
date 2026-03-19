#!/usr/bin/env python3
"""
Import Garmin FIT files into the local SQLite data hub.

Usage:
    python import_garmin_fit.py
    python import_garmin_fit.py --db data_hub.db --fit-root garmin-data
"""

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fit_summary import canonicalize_fit, parse_fit


DEFAULT_DB_PATH = Path("data_hub.db")
DEFAULT_FIT_ROOT = Path("raw/garmin/inbox")
DEFAULT_SCHEMA_PATH = Path("schema.sql")
DEFAULT_ARCHIVE_ROOT = Path("raw/garmin/archive")
DEFAULT_FAILED_ROOT = Path("raw/garmin/failed")


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def iso_to_local_date(iso_value, timezone_name):
    if not iso_value:
        return None
    dt = datetime.fromisoformat(iso_value)
    return dt.astimezone(ZoneInfo(timezone_name)).date().isoformat()


def compute_sha256(filepath):
    hasher = hashlib.sha256()
    with open(filepath, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_folder_date(folder_name):
    for fmt in ("%m-%d-%Y", "%-m-%d-%Y", "%m-%-d-%Y", "%-m-%-d-%Y"):
        try:
            return datetime.strptime(folder_name, fmt).date().isoformat()
        except ValueError:
            continue
    parts = folder_name.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        month, day, year = parts
        try:
            return datetime(int(year), int(month), int(day)).date().isoformat()
        except ValueError:
            return None
    return None


def extract_date_hint_from_filename(filename):
    parts = filename.split("__", 1)
    if len(parts) != 2:
        return None
    return parse_folder_date(parts[0])


def ensure_schema(connection, schema_path):
    schema_sql = Path(schema_path).read_text(encoding="utf-8")
    connection.executescript(schema_sql)


def start_ingestion_run(connection, source_type, run_mode, notes):
    cursor = connection.execute(
        """
        INSERT INTO ingestion_runs(source_type, run_mode, notes)
        VALUES(?, ?, ?)
        """,
        (source_type, run_mode, notes),
    )
    return cursor.lastrowid


def finish_ingestion_run(
    connection,
    run_id,
    status,
    scanned_file_count,
    imported_count,
    skipped_count,
    failed_count,
):
    connection.execute(
        """
        UPDATE ingestion_runs
        SET completed_at = CURRENT_TIMESTAMP,
            status = ?,
            scanned_file_count = ?,
            imported_count = ?,
            skipped_count = ?,
            failed_count = ?
        WHERE id = ?
        """,
        (status, scanned_file_count, imported_count, skipped_count, failed_count, run_id),
    )


def log_ingestion_file_event(
    connection,
    run_id,
    file_path,
    event_type,
    message=None,
    source_file_id=None,
    file_hash=None,
):
    connection.execute(
        """
        INSERT INTO ingestion_run_files(
            ingestion_run_id,
            source_file_id,
            file_path,
            file_hash,
            event_type,
            message
        )
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (run_id, source_file_id, str(file_path), file_hash, event_type, message),
    )


def get_or_create_athlete(connection, display_name, timezone_name):
    row = connection.execute(
        """
        SELECT id
        FROM athletes
        WHERE display_name = ?
        ORDER BY id
        LIMIT 1
        """,
        (display_name,),
    ).fetchone()
    if row:
        connection.execute(
            """
            UPDATE athletes
            SET timezone = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (timezone_name, row[0]),
        )
        return row[0]

    cursor = connection.execute(
        """
        INSERT INTO athletes(display_name, timezone)
        VALUES(?, ?)
        """,
        (display_name, timezone_name),
    )
    return cursor.lastrowid


def get_or_create_data_source(connection):
    row = connection.execute(
        """
        SELECT id
        FROM data_sources
        WHERE source_type = ? AND source_name = ?
        """,
        ("garmin_fit", "Garmin FIT Import"),
    ).fetchone()
    if row:
        return row[0]

    cursor = connection.execute(
        """
        INSERT INTO data_sources(source_type, source_name, connector_version)
        VALUES(?, ?, ?)
        """,
        ("garmin_fit", "Garmin FIT Import", "v1"),
    )
    return cursor.lastrowid


def upsert_source_file(connection, data_source_id, athlete_id, fit_path, file_hash):
    row = connection.execute(
        """
        SELECT id, status
        FROM source_files
        WHERE file_hash = ? OR file_path = ?
        LIMIT 1
        """,
        (file_hash, str(fit_path)),
    ).fetchone()

    if row:
        connection.execute(
            """
            UPDATE source_files
            SET athlete_id = ?,
                file_name = ?,
                file_path = ?,
                file_hash = ?,
                file_size_bytes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                athlete_id,
                fit_path.name,
                str(fit_path),
                file_hash,
                fit_path.stat().st_size,
                row[0],
            ),
        )
        return row[0], row[1]

    cursor = connection.execute(
        """
        INSERT INTO source_files(
            data_source_id,
            athlete_id,
            file_name,
            file_path,
            file_hash,
            file_size_bytes,
            status
        )
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data_source_id,
            athlete_id,
            fit_path.name,
            str(fit_path),
            file_hash,
            fit_path.stat().st_size,
            "discovered",
        ),
    )
    return cursor.lastrowid, "discovered"


def update_source_file_path(connection, source_file_id, fit_path):
    connection.execute(
        """
        UPDATE source_files
        SET file_name = ?,
            file_path = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (fit_path.name, str(fit_path), source_file_id),
    )


def delete_existing_import(connection, source_file_id):
    connection.execute(
        "DELETE FROM activities WHERE source_file_id = ?",
        (source_file_id,),
    )


def insert_activity(connection, athlete_id, source_file_id, activity):
    cursor = connection.execute(
        """
        INSERT INTO activities(
            athlete_id,
            source_file_id,
            source_activity_id,
            activity_type,
            sport,
            sub_sport,
            started_at_utc,
            ended_at_utc,
            timezone,
            duration_seconds,
            moving_time_seconds,
            distance_m,
            calories_kcal,
            total_ascent_m,
            total_descent_m,
            avg_speed_mps,
            max_speed_mps,
            avg_heart_rate_bpm,
            max_heart_rate_bpm,
            avg_cadence_spm,
            max_cadence_spm,
            training_load,
            device_name
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            athlete_id,
            source_file_id,
            None,
            activity["activity_type"],
            activity["sport"],
            activity["sub_sport"],
            activity["started_at_utc"],
            activity["ended_at_utc"],
            activity["timezone"],
            activity["duration_seconds"],
            activity["moving_time_seconds"],
            activity["distance_m"],
            activity["calories_kcal"],
            activity["total_ascent_m"],
            activity["total_descent_m"],
            activity["avg_speed_mps"],
            activity["max_speed_mps"],
            activity["avg_heart_rate_bpm"],
            activity["max_heart_rate_bpm"],
            activity["avg_cadence_spm"],
            activity["max_cadence_spm"],
            activity["training_load"],
            activity["device_name"],
        ),
    )
    return cursor.lastrowid


def insert_laps(connection, activity_id, laps):
    connection.executemany(
        """
        INSERT INTO laps(
            activity_id,
            lap_index,
            started_at_utc,
            ended_at_utc,
            duration_seconds,
            distance_m,
            avg_speed_mps,
            max_speed_mps,
            avg_heart_rate_bpm,
            max_heart_rate_bpm,
            avg_cadence_spm,
            lap_type
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                activity_id,
                lap["lap_index"],
                lap["started_at_utc"],
                lap["ended_at_utc"],
                lap["duration_seconds"],
                lap["distance_m"],
                lap["avg_speed_mps"],
                lap["max_speed_mps"],
                lap["avg_heart_rate_bpm"],
                lap["max_heart_rate_bpm"],
                lap["avg_cadence_spm"],
                lap["lap_type"],
            )
            for lap in laps
        ],
    )


def insert_samples(connection, activity_id, samples):
    connection.executemany(
        """
        INSERT INTO activity_samples(
            activity_id,
            sample_timestamp_utc,
            elapsed_seconds,
            distance_m,
            speed_mps,
            heart_rate_bpm,
            cadence_spm,
            power_watts,
            altitude_m,
            temperature_c,
            latitude_semicircles,
            longitude_semicircles
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                activity_id,
                sample["sample_timestamp_utc"],
                sample["elapsed_seconds"],
                sample["distance_m"],
                sample["speed_mps"],
                sample["heart_rate_bpm"],
                sample["cadence_spm"],
                sample["power_watts"],
                sample["altitude_m"],
                sample["temperature_c"],
                sample["latitude_semicircles"],
                sample["longitude_semicircles"],
            )
            for sample in samples
        ],
    )


def mark_source_file(connection, source_file_id, status):
    connection.execute(
        """
        UPDATE source_files
        SET status = ?,
            imported_at = CASE WHEN ? = 'imported' THEN CURRENT_TIMESTAMP ELSE imported_at END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, status, source_file_id),
    )


def discover_fit_files(root_path):
    return sorted(Path(root_path).rglob("*.fit"))


def lookup_source_file(connection, file_hash, fit_path):
    return connection.execute(
        """
        SELECT id, status, file_path, imported_at
        FROM source_files
        WHERE file_hash = ? OR file_path = ?
        LIMIT 1
        """,
        (file_hash, str(fit_path)),
    ).fetchone()


def inspect_fit_file(connection, fit_path, timezone_name):
    file_hash = compute_sha256(fit_path)
    source_row = lookup_source_file(connection, file_hash, fit_path)
    records, laps, sessions = parse_fit(fit_path)
    warnings = []
    errors = []

    if len(sessions) == 0:
        errors.append("No session messages found in FIT file")
        canonical = None
    else:
        canonical = canonicalize_fit(fit_path, athlete_timezone=timezone_name)
        if len(sessions) > 1:
            warnings.append(
                f"Found {len(sessions)} session messages; importer currently uses the first session"
            )

    date_hint = extract_date_hint_from_filename(fit_path.name)
    activity_date = None
    activity_type = None
    sport = None
    if canonical is not None and canonical["activity"]["started_at_utc"]:
        activity_date = iso_to_local_date(
            canonical["activity"]["started_at_utc"],
            canonical["activity"]["timezone"] or timezone_name,
        )
        activity_type = canonical["activity"]["activity_type"]
        sport = canonical["activity"]["sport"]
        if date_hint is not None and date_hint != activity_date:
            warnings.append(
                f"Inbox date hint {date_hint} does not match activity date {activity_date}"
            )

    duplicate_status = "new"
    source_file_id = None
    imported_at = None
    known_path = None
    if source_row:
        source_file_id, known_status, known_path, imported_at = source_row
        known_path = str(known_path)
        duplicate_status = known_status or "known"
        if known_path != str(fit_path):
            warnings.append(f"Known duplicate of {known_path}")

    return {
        "file_path": str(fit_path),
        "file_name": fit_path.name,
        "date_hint": date_hint,
        "file_hash": file_hash,
        "file_size_bytes": fit_path.stat().st_size,
        "source_file_id": source_file_id,
        "duplicate_status": duplicate_status,
        "imported_at": imported_at,
        "session_count": len(sessions),
        "lap_count": len(laps),
        "record_count": len(records),
        "activity_date": activity_date,
        "activity_type": activity_type,
        "sport": sport,
        "warnings": warnings,
        "errors": errors,
    }


def build_preview(connection, fit_files, timezone_name):
    rows = [inspect_fit_file(connection, fit_path, timezone_name) for fit_path in fit_files]
    summary = {
        "scanned_file_count": len(rows),
        "new_file_count": sum(1 for row in rows if row["duplicate_status"] == "new"),
        "imported_duplicate_count": sum(
            1 for row in rows if row["duplicate_status"] == "imported"
        ),
        "other_known_count": sum(
            1 for row in rows if row["duplicate_status"] not in {"new", "imported"}
        ),
        "warning_count": sum(1 for row in rows if row["warnings"]),
        "error_count": sum(1 for row in rows if row["errors"]),
    }
    return {"summary": summary, "files": rows}


def print_preview(preview):
    summary = preview["summary"]
    print(
        "Preview:"
        f" scanned={summary['scanned_file_count']}"
        f" new={summary['new_file_count']}"
        f" imported_duplicates={summary['imported_duplicate_count']}"
        f" warnings={summary['warning_count']}"
        f" errors={summary['error_count']}"
    )
    for row in preview["files"]:
        status = row["duplicate_status"].upper()
        activity_label = row["activity_type"] or "unknown"
        date_label = row["activity_date"] or "unknown-date"
        print(
            f"{status} {row['file_path']} "
            f"(date={date_label}, type={activity_label}, sessions={row['session_count']})"
        )
        for warning in row["warnings"]:
            print(f"  WARN: {warning}")
        for error in row["errors"]:
            print(f"  ERROR: {error}")


def preview_event_type(row):
    if row["errors"]:
        return "preview_error"
    if row["warnings"]:
        return "preview_warning"
    if row["duplicate_status"] == "new":
        return "preview_new"
    return "preview_known"


def ensure_directory(path):
    path.mkdir(parents=True, exist_ok=True)


def safe_move_file(source_path, target_path):
    ensure_directory(target_path.parent)
    candidate = target_path
    suffix = 1
    while candidate.exists():
        candidate = candidate.with_name(
            f"{target_path.stem}_{suffix}{target_path.suffix}"
        )
        suffix += 1
    shutil.move(str(source_path), str(candidate))
    return candidate


def build_archive_destination(archive_root, canonical_activity, source_path):
    activity_date = canonical_activity["activity"]["started_at_utc"]
    if activity_date:
        date_dir = activity_date[:10]
    else:
        date_dir = utc_now_iso()[:10]
    return Path(archive_root) / date_dir / source_path.name


def build_duplicate_archive_destination(archive_root, source_path):
    date_hint = extract_date_hint_from_filename(source_path.name)
    date_dir = date_hint if date_hint else utc_now_iso()[:10]
    return Path(archive_root) / date_dir / source_path.name


def move_imported_file(connection, source_file_id, source_path, archive_root, canonical):
    destination = build_archive_destination(archive_root, canonical, source_path)
    final_path = safe_move_file(source_path, destination)
    update_source_file_path(connection, source_file_id, final_path)
    return final_path


def move_failed_file(connection, source_file_id, source_path, failed_root):
    destination = Path(failed_root) / source_path.name
    final_path = safe_move_file(source_path, destination)
    if source_file_id is not None:
        update_source_file_path(connection, source_file_id, final_path)
    return final_path


def move_known_duplicate_file(source_path, archive_root):
    destination = build_duplicate_archive_destination(archive_root, source_path)
    return safe_move_file(source_path, destination)


def import_fit_file(
    connection,
    athlete_id,
    data_source_id,
    fit_path,
    timezone_name,
    force,
):
    file_hash = compute_sha256(fit_path)
    source_file_id, status = upsert_source_file(
        connection, data_source_id, athlete_id, fit_path, file_hash
    )

    if status == "imported" and not force:
        return {
            "status": "skipped",
            "source_file_id": source_file_id,
            "file_hash": file_hash,
            "canonical": None,
        }

    if force:
        delete_existing_import(connection, source_file_id)

    canonical = canonicalize_fit(fit_path, athlete_timezone=timezone_name)
    activity_id = insert_activity(connection, athlete_id, source_file_id, canonical["activity"])
    insert_laps(connection, activity_id, canonical["laps"])
    insert_samples(connection, activity_id, canonical["samples"])
    mark_source_file(connection, source_file_id, "imported")

    return {
        "status": "imported",
        "source_file_id": source_file_id,
        "file_hash": file_hash,
        "canonical": canonical,
        "activity_id": activity_id,
        "lap_count": len(canonical["laps"]),
        "sample_count": len(canonical["samples"]),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Import Garmin FIT files into SQLite.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    parser.add_argument(
        "--fit-root",
        default=str(DEFAULT_FIT_ROOT),
        help="Root directory that contains .fit files.",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Path to the schema.sql file.",
    )
    parser.add_argument(
        "--athlete-name",
        default="Primary Athlete",
        help="Display name to use for the athlete row.",
    )
    parser.add_argument(
        "--timezone",
        default="America/Chicago",
        help="Timezone stored on activities and athlete rows.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-import files that were already imported.",
    )
    parser.add_argument(
        "--archive-root",
        default="",
        help="If set, successfully imported files are moved into this archive root.",
    )
    parser.add_argument(
        "--failed-root",
        default="",
        help="If set, failed files are moved into this folder.",
    )
    parser.add_argument(
        "--run-mode",
        default="direct",
        choices=["direct", "inbox"],
        help="Use 'inbox' when importing from a raw drop folder and moving files after processing.",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional notes stored on the ingestion run.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Scan FIT files, report duplicates and mismatches, and exit without importing.",
    )
    parser.add_argument(
        "--preview-json",
        action="store_true",
        help="Emit preview output as JSON. Implies --preview.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    db_path = Path(args.db)
    fit_root = Path(args.fit_root)
    schema_path = Path(args.schema)
    archive_root = Path(args.archive_root) if args.archive_root else None
    failed_root = Path(args.failed_root) if args.failed_root else None

    if args.run_mode == "inbox":
        archive_root = archive_root or DEFAULT_ARCHIVE_ROOT
        failed_root = failed_root or DEFAULT_FAILED_ROOT

    if not fit_root.exists():
        raise SystemExit(f"FIT root does not exist: {fit_root}")
    if not schema_path.exists():
        raise SystemExit(f"Schema file does not exist: {schema_path}")

    fit_files = discover_fit_files(fit_root)
    if not fit_files:
        raise SystemExit(f"No .fit files found under: {fit_root}")

    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        ensure_schema(connection, schema_path)
        if args.preview_json:
            args.preview = True
        if args.preview:
            preview = build_preview(connection, fit_files, args.timezone)
            run_id = start_ingestion_run(
                connection,
                "garmin_fit",
                f"{args.run_mode}_preview",
                args.notes or f"preview fit_root={fit_root}",
            )
            with connection:
                for row in preview["files"]:
                    notes = []
                    if row["warnings"]:
                        notes.extend(f"WARN: {warning}" for warning in row["warnings"])
                    if row["errors"]:
                        notes.extend(f"ERROR: {error}" for error in row["errors"])
                    log_ingestion_file_event(
                        connection,
                        run_id,
                        row["file_path"],
                        preview_event_type(row),
                        message=" | ".join(notes) if notes else None,
                        source_file_id=row["source_file_id"],
                        file_hash=row["file_hash"],
                    )
                finish_ingestion_run(
                    connection,
                    run_id,
                    "preview_completed"
                    if preview["summary"]["error_count"] == 0
                    else "preview_completed_with_errors",
                    preview["summary"]["scanned_file_count"],
                    0,
                    preview["summary"]["imported_duplicate_count"],
                    preview["summary"]["error_count"],
                )
            if args.preview_json:
                print(json.dumps(preview, indent=2))
            else:
                print_preview(preview)
            return
        if archive_root is not None:
            ensure_directory(archive_root)
        if failed_root is not None:
            ensure_directory(failed_root)
        athlete_id = get_or_create_athlete(connection, args.athlete_name, args.timezone)
        data_source_id = get_or_create_data_source(connection)
        run_id = start_ingestion_run(
            connection,
            "garmin_fit",
            args.run_mode,
            args.notes or f"fit_root={fit_root}",
        )

        imported = 0
        skipped = 0
        failed = 0
        total_samples = 0
        total_laps = 0

        for fit_path in fit_files:
            try:
                with connection:
                    result = import_fit_file(
                        connection,
                        athlete_id,
                        data_source_id,
                        fit_path,
                        args.timezone,
                        args.force,
                    )
                    log_ingestion_file_event(
                        connection,
                        run_id,
                        fit_path,
                        result["status"],
                        source_file_id=result["source_file_id"],
                        file_hash=result.get("file_hash"),
                    )

                    if result["status"] == "skipped":
                        skipped += 1
                        if archive_root is not None and fit_path.exists():
                            archived_duplicate_path = move_known_duplicate_file(
                                fit_path,
                                archive_root,
                            )
                            log_ingestion_file_event(
                                connection,
                                run_id,
                                archived_duplicate_path,
                                "archived_duplicate",
                                message=f"Moved duplicate from {fit_path}",
                                source_file_id=result["source_file_id"],
                                file_hash=result["file_hash"],
                            )
                        print(f"SKIP {fit_path}")
                        continue

                    imported += 1
                    total_laps += result["lap_count"]
                    total_samples += result["sample_count"]

                    if archive_root is not None:
                        archived_path = move_imported_file(
                            connection,
                            result["source_file_id"],
                            fit_path,
                            archive_root,
                            result["canonical"],
                        )
                        log_ingestion_file_event(
                            connection,
                            run_id,
                            archived_path,
                            "archived",
                            message=f"Moved from {fit_path}",
                            source_file_id=result["source_file_id"],
                            file_hash=result["file_hash"],
                        )

                print(
                    f"IMPORTED {fit_path} "
                    f"(activity_id={result['activity_id']}, laps={result['lap_count']}, "
                    f"samples={result['sample_count']})"
                )
            except Exception as exc:
                failed += 1
                source_file_id = None
                file_hash = None
                try:
                    file_hash = compute_sha256(fit_path) if fit_path.exists() else None
                    existing = connection.execute(
                        """
                        SELECT id
                        FROM source_files
                        WHERE file_hash = ? OR file_path = ?
                        LIMIT 1
                        """,
                        (file_hash, str(fit_path)),
                    ).fetchone()
                    if existing:
                        source_file_id = existing[0]
                        with connection:
                            mark_source_file(connection, source_file_id, "failed")
                except Exception:
                    pass

                failed_path = fit_path
                if failed_root is not None and fit_path.exists():
                    with connection:
                        failed_path = move_failed_file(
                            connection,
                            source_file_id,
                            fit_path,
                            failed_root,
                        )

                with connection:
                    log_ingestion_file_event(
                        connection,
                        run_id,
                        failed_path,
                        "failed",
                        message=str(exc),
                        source_file_id=source_file_id,
                        file_hash=file_hash,
                    )
                print(f"FAILED {fit_path}: {exc}")

        with connection:
            finish_ingestion_run(
                connection,
                run_id,
                "completed" if failed == 0 else "completed_with_errors",
                len(fit_files),
                imported,
                skipped,
                failed,
            )

        print(
            f"Done. imported={imported} skipped={skipped} failed={failed} "
            f"laps={total_laps} samples={total_samples} db={db_path}"
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
