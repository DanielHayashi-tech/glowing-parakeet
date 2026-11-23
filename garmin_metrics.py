"""Store Garmin's own activity-level values and keep the original list JSON.

Garmin's activity list carries values the FIT parser cannot reproduce (training effect,
training load, heart-rate-zone time, the activity name) and the device's local start time.
These are authoritative, so they are written onto the matching activity. The raw JSON is
kept in garmin_activity_raw so any field can be re-extracted later without asking Garmin again.

garmin_activity_raw.fit_status makes missing data explicit:
  pending      seen in Garmin's list, FIT not imported yet
  imported     a matching activity row exists
  no_original  Garmin has no original file for it (for example a manual entry)
  invalid      a download arrived but did not contain a usable FIT file
"""

import json
from datetime import datetime, timedelta, timezone


DISTANCE_TOLERANCE = 0.005   # 0.5%
DISTANCE_MIN_METERS = 10
DURATION_TOLERANCE_SECONDS = 1
START_TOLERANCE_SECONDS = 2


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def offset_minutes(item):
    """UTC offset Garmin recorded for this activity, from its own local and GMT start times."""
    try:
        local = datetime.strptime(item["startTimeLocal"], "%Y-%m-%d %H:%M:%S")
        gmt = datetime.strptime(item["startTimeGMT"], "%Y-%m-%d %H:%M:%S")
    except (KeyError, TypeError, ValueError):
        return None
    return int((local - gmt).total_seconds() // 60)


def summary_values(item):
    """Columns to write on the activity row, taken from one Garmin list item."""
    type_key = (item.get("activityType") or {}).get("typeKey")
    local = item.get("startTimeLocal")
    values = {
        "garmin_type_key": type_key,
        "activity_name": item.get("activityName"),
        "start_time_local": local.replace(" ", "T") if isinstance(local, str) else None,
        "local_date": local[:10] if isinstance(local, str) else None,
        "utc_offset_minutes": offset_minutes(item),
        "utc_offset_source": "garmin_api",
        "aerobic_training_effect": number(item.get("aerobicTrainingEffect")),
        "anaerobic_training_effect": number(item.get("anaerobicTrainingEffect")),
        "training_effect_label": item.get("trainingEffectLabel"),
        "training_load": number(item.get("activityTrainingLoad")),
        "avg_heart_rate_bpm": number(item.get("averageHR")),
        "max_heart_rate_bpm": number(item.get("maxHR")),
        "avg_cadence_spm": number(item.get("averageRunningCadenceInStepsPerMinute")),
    }
    for zone in range(1, 6):
        values[f"hr_zone{zone}_seconds"] = number(item.get(f"hrTimeInZone_{zone}"))
    return values


def apply_items(connection, items, now=None):
    """Upsert raw JSON for every item and update matching activities. Returns counts."""
    now = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    counts = {"items": 0, "activities_updated": 0, "not_imported": 0, "garmin_adjusted": 0, "start_corrected": 0}
    for item in items:
        garmin_id = item.get("activityId")
        if not isinstance(garmin_id, int):
            continue
        counts["items"] += 1
        connection.execute(
            """
            INSERT INTO garmin_activity_raw(garmin_activity_id, payload, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(garmin_activity_id) DO UPDATE SET payload = excluded.payload, fetched_at = excluded.fetched_at
            """,
            (garmin_id, json.dumps(item), now),
        )
        row = connection.execute(
            "SELECT id FROM activities WHERE garmin_activity_id = ?", (garmin_id,)
        ).fetchone()
        if not row:
            counts["not_imported"] += 1
            continue
        values = summary_values(item)
        # Garmin's value wins only when Garmin actually reports one; never overwrite with NULL.
        values = {name: value for name, value in values.items() if value is not None}
        assignments = ", ".join(f"{name} = ?" for name in values)
        connection.execute(
            f"UPDATE activities SET {assignments}, metrics_fetched_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [*values.values(), now, row[0]],
        )
        changed = reconcile_core_values(connection, row[0], item)
        counts["garmin_adjusted"] += changed["adjusted"]
        counts["start_corrected"] += changed["start"]
        set_fit_status(connection, garmin_id, "imported")
        counts["activities_updated"] += 1
    connection.commit()
    return counts


def reconcile_core_values(connection, row_id, item):
    """Make distance, duration and start follow Garmin, and keep the FIT's own values.

    Garmin's servers are what Garmin Connect shows, and they can differ from the uploaded FIT
    (a treadmill distance calibrated after the run, a trimmed activity, an indoor ride whose FIT
    carries no distance). garmin_adjusted = 1 marks a difference beyond tolerance so analysis can
    tell; fit_distance_m / fit_duration_seconds keep the original. Returns what changed.
    """
    row = connection.execute(
        "SELECT started_at_utc, distance_m, duration_seconds, fit_distance_m, fit_duration_seconds FROM activities WHERE id = ?",
        (row_id,),
    ).fetchone()
    started, distance, duration, fit_distance, fit_duration = row
    # First time through, the stored values are still the FIT's own: preserve them.
    fit_distance = distance if fit_distance is None else fit_distance
    fit_duration = duration if fit_duration is None else fit_duration

    garmin_distance = number(item.get("distance"))
    garmin_duration = number(item.get("duration"))
    adjusted = 0
    changed = {"start": False}
    if garmin_distance is not None:
        if fit_distance is None or abs(garmin_distance - fit_distance) > max(DISTANCE_MIN_METERS, DISTANCE_TOLERANCE * garmin_distance):
            adjusted = 1
        distance = garmin_distance
    if garmin_duration is not None:
        if fit_duration is None or abs(garmin_duration - fit_duration) > DURATION_TOLERANCE_SECONDS:
            adjusted = 1
        duration = garmin_duration

    try:
        garmin_start = datetime.strptime(item["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if abs((datetime.fromisoformat(started) - garmin_start).total_seconds()) > START_TOLERANCE_SECONDS:
            started = garmin_start.isoformat()
            changed["start"] = True
    except (KeyError, TypeError, ValueError):
        pass
    ended = (datetime.fromisoformat(started) + timedelta(seconds=duration)).isoformat() if duration is not None else None

    connection.execute(
        """
        UPDATE activities
        SET started_at_utc = ?, ended_at_utc = COALESCE(?, ended_at_utc), distance_m = ?, duration_seconds = ?,
            moving_time_seconds = ?, fit_distance_m = ?, fit_duration_seconds = ?, garmin_adjusted = ?
        WHERE id = ?
        """,
        (started, ended, distance, duration, number(item.get("movingDuration")) or duration, fit_distance, fit_duration, adjusted, row_id),
    )
    changed["adjusted"] = bool(adjusted)
    return changed


def set_fit_status(connection, garmin_id, status, detail=None):
    connection.execute(
        """
        UPDATE garmin_activity_raw
        SET fit_status = ?, fit_status_detail = ?, status_updated_at = CURRENT_TIMESTAMP
        WHERE garmin_activity_id = ?
        """,
        (status, detail, garmin_id),
    )


def record_unavailable(connection, no_original_ids, invalid_ids):
    for garmin_id in no_original_ids:
        set_fit_status(connection, garmin_id, "no_original", "Garmin has no original file for this activity")
    for garmin_id in invalid_ids:
        set_fit_status(connection, garmin_id, "invalid", "download did not contain a usable FIT file")
    connection.commit()
