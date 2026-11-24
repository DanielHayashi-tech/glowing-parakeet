"""Training context for an AI coach, built from the validated Corre Cortes database.

Read-only. Everything here is computed from stored facts (see docs/milestone-1-garmin-pipeline.md):
dates are each activity's own local date, distances follow Garmin, and nothing is estimated.
Anything we do not have is reported as missing (null plus a reason), never as zero.
"""

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

METERS_PER_MILE = 1609.344
FEET_PER_METER = 3.28084
STALE_AFTER_HOURS = 3          # the sync runs hourly; a couple of skipped hours is normal
WINDOW_DAYS = (7, 14, 28)
WEEKS_SHOWN = 8
LONG_RUN_WEEKS = 6
DEFAULT_RECENT = 10
MAX_RECENT = 25
STATUS_PATH = "temp/last_sync.json"
UNITS = {"distance": "miles", "elevation": "feet", "duration": "minutes", "pace": "min/mile", "heart_rate": "bpm"}


# ---------- shared date helpers (also used by validate_garmin.py) ----------

def monday_of(day):
    return day - timedelta(days=day.weekday())


def weekly_running_miles(entries, weeks, today):
    """{monday: miles} for the last `weeks` complete Monday-Sunday weeks.

    entries are (local_date 'YYYY-MM-DD', meters) for running activities only.
    """
    last_complete_monday = monday_of(today) - timedelta(days=7)
    mondays = [last_complete_monday - timedelta(days=7 * k) for k in range(weeks)]
    totals = {monday: 0.0 for monday in mondays}
    for local_date, meters in entries:
        monday = monday_of(date.fromisoformat(local_date))
        if monday in totals:
            totals[monday] += (meters or 0) / METERS_PER_MILE
    return totals


# ---------- small helpers ----------

def miles(meters):
    return None if meters is None else round(meters / METERS_PER_MILE, 2)


def minutes(seconds):
    return None if seconds is None else round(seconds / 60, 1)


def pace_fields(distance_m, duration_s):
    """(pace as min/mile float, 'm:ss' string), or (None, None) when it cannot be computed honestly."""
    if not distance_m or not duration_s or distance_m < 100:
        return None, None
    per_mile = (duration_s / 60) / (distance_m / METERS_PER_MILE)
    whole = int(per_mile)
    seconds = round((per_mile - whole) * 60)
    if seconds == 60:
        whole, seconds = whole + 1, 0
    return round(per_mile, 2), f"{whole}:{seconds:02d}"


def is_run(row):
    return row["activity_type"] == "running"


def is_strength(row):
    return row["activity_type"] == "training" and row["sub_sport"] == "strength_training"


def flags_for(row):
    """Reasons a number on this activity needs care. Empty when nothing to flag."""
    flags = []
    if row["sub_sport"] == "treadmill":
        flags.append("treadmill")
    if row["garmin_adjusted"] == 1:
        flags.append("distance_or_duration_from_garmin_not_the_fit_file")
    if row["lap_distance_adjusted"] == 1:
        flags.append("lap_distances_unreliable")
    return flags


def activity_summary(row):
    pace_value, pace_text = pace_fields(row["distance_m"], row["duration_seconds"]) if is_run(row) else (None, None)
    return {
        "garmin_activity_id": row["garmin_activity_id"],
        "local_date": row["local_date"],
        "local_start": row["start_time_local"],
        "type": row["garmin_type_key"] or row["activity_type"],
        "name": row["activity_name"],
        "distance_miles": miles(row["distance_m"]),
        "duration_minutes": minutes(row["duration_seconds"]),
        "pace_min_per_mile": pace_value,
        "pace": pace_text,
        "avg_heart_rate_bpm": None if row["avg_heart_rate_bpm"] is None else round(row["avg_heart_rate_bpm"]),
        "max_heart_rate_bpm": None if row["max_heart_rate_bpm"] is None else round(row["max_heart_rate_bpm"]),
        "elevation_gain_feet": None if row["total_ascent_m"] is None else round(row["total_ascent_m"] * FEET_PER_METER),
        "aerobic_training_effect": None if row["aerobic_training_effect"] is None else round(row["aerobic_training_effect"], 1),
        "anaerobic_training_effect": None if row["anaerobic_training_effect"] is None else round(row["anaerobic_training_effect"], 1),
        "garmin_training_load": None if row["training_load"] is None else round(row["training_load"], 1),
        "flags": flags_for(row),
    }


# ---------- aggregates ----------

def window_summary(rows, first_day, last_day):
    selected = [r for r in rows if first_day <= r["local_date"] <= last_day]
    days = (date.fromisoformat(last_day) - date.fromisoformat(first_day)).days + 1
    runs = [r for r in selected if is_run(r)]
    run_meters = sum(r["distance_m"] or 0 for r in runs)
    run_seconds = sum(r["duration_seconds"] or 0 for r in runs)
    pace_value, pace_text = pace_fields(run_meters, run_seconds)

    hr_seconds = [(r["avg_heart_rate_bpm"], r["duration_seconds"]) for r in runs if r["avg_heart_rate_bpm"] and r["duration_seconds"]]
    avg_hr = round(sum(h * s for h, s in hr_seconds) / sum(s for _, s in hr_seconds)) if hr_seconds else None

    zone_runs = [r for r in runs if all(r[f"hr_zone{z}_seconds"] is not None for z in range(1, 6))]
    zone_minutes = None
    if zone_runs:
        zone_minutes = {f"zone{z}": round(sum(r[f"hr_zone{z}_seconds"] for r in zone_runs) / 60) for z in range(1, 6)}

    strength = [r for r in selected if is_strength(r)]
    other = [r for r in selected if not is_run(r) and not is_strength(r)]
    loads = [r["training_load"] for r in selected if r["training_load"] is not None]
    active_days = {r["local_date"] for r in selected}

    return {
        "days": days,
        "from": first_day,
        "to": last_day,
        "running": {
            "runs": len(runs),
            "miles": round(run_meters / METERS_PER_MILE, 2),
            "minutes": round(run_seconds / 60, 1),
            "miles_per_week_equivalent": round(run_meters / METERS_PER_MILE * 7 / days, 1),
            "longest_run_miles": miles(max((r["distance_m"] or 0 for r in runs), default=None)) if runs else None,
            "avg_pace_min_per_mile": pace_value,
            "avg_pace": pace_text,
            "avg_heart_rate_bpm": avg_hr,
            "elevation_gain_feet": round(sum((r["total_ascent_m"] or 0) for r in runs) * FEET_PER_METER),
            "treadmill_runs": sum(1 for r in runs if r["sub_sport"] == "treadmill"),
            "heart_rate_zone_minutes": zone_minutes,
            "runs_without_heart_rate_zones": len(runs) - len(zone_runs),
        },
        "strength_sessions": len(strength),
        "strength_minutes": round(sum(r["duration_seconds"] or 0 for r in strength) / 60, 1),
        "other_activities": {"count": len(other), "minutes": round(sum(r["duration_seconds"] or 0 for r in other) / 60, 1)},
        "active_days": len(active_days),
        "rest_days": days - len(active_days),
        "garmin_training_load_total": round(sum(loads), 1) if loads else None,
        "activities_without_garmin_training_load": len(selected) - len(loads),
    }


def weekly_breakdown(rows, today):
    weeks = []
    for k in range(WEEKS_SHOWN):
        monday = monday_of(today) - timedelta(days=7 * k)
        sunday = monday + timedelta(days=6)
        in_week = [r for r in rows if monday.isoformat() <= r["local_date"] <= sunday.isoformat()]
        runs = [r for r in in_week if is_run(r)]
        weeks.append({
            "week_start": monday.isoformat(),
            "week_end": sunday.isoformat(),
            "is_current_week": k == 0,
            "days_counted": (today - monday).days + 1 if k == 0 else 7,
            "runs": len(runs),
            "miles": round(sum(r["distance_m"] or 0 for r in runs) / METERS_PER_MILE, 2),
            "minutes": round(sum(r["duration_seconds"] or 0 for r in runs) / 60, 1),
            "longest_run_miles": miles(max((r["distance_m"] or 0 for r in runs))) if runs else None,
            "strength_sessions": sum(1 for r in in_week if is_strength(r)),
        })
    return weeks


def longest_run_each_week(rows, today):
    """The longest run of each of the last weeks, newest first. A rule, not a judgment: the longest
    run that week, whatever its length. Weeks without a run are omitted."""
    result = []
    for k in range(LONG_RUN_WEEKS):
        monday = monday_of(today) - timedelta(days=7 * k)
        sunday = monday + timedelta(days=6)
        runs = [r for r in rows if is_run(r) and monday.isoformat() <= r["local_date"] <= sunday.isoformat()]
        if runs:
            longest = max(runs, key=lambda r: r["distance_m"] or 0)
            entry = activity_summary(longest)
            entry["week_start"] = monday.isoformat()
            result.append(entry)
    return result


# ---------- freshness ----------

def load_status(path=STATUS_PATH):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def parse_utc(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def freshness(status, latest_row, now):
    notes = []
    last_success = parse_utc((status or {}).get("last_success_at"))
    hours = round((now - last_success).total_seconds() / 3600, 1) if last_success else None
    stale = True if hours is None else hours > STALE_AFTER_HOURS
    if status is None:
        notes.append("No sync status file was found, so freshness is unknown. Treat the data as possibly stale.")
    elif last_success is None:
        notes.append("No successful Garmin sync has been recorded. Treat the data as possibly stale.")
    elif stale:
        notes.append(f"The last successful Garmin sync was {hours} hours ago; activities from the last few hours may be missing.")
    if status and status.get("ok") is False:
        notes.append(f"The most recent sync attempt failed: {status.get('message')}")
    latest = None
    if latest_row:
        started = parse_utc(latest_row["started_at_utc"])
        latest = {
            "local_date": latest_row["local_date"],
            "local_start": latest_row["start_time_local"],
            "type": latest_row["garmin_type_key"] or latest_row["activity_type"],
            "hours_ago": round((now - started).total_seconds() / 3600, 1) if started else None,
        }
    return {
        "last_successful_sync_utc": (status or {}).get("last_success_at"),
        "hours_since_last_successful_sync": hours,
        "stale": stale,
        "stale_after_hours": STALE_AFTER_HOURS,
        "last_attempt_utc": (status or {}).get("finished_at"),
        "last_attempt_ok": (status or {}).get("ok"),
        "latest_activity": latest,
        "notes": notes,
    }


# ---------- recovery ----------

SHORT_SLEEP_NIGHT_HOURS = 6.5
VERY_SHORT_SLEEP_HOURS = 6.0
HRV_TREND_DROP = 0.20          # 7-day average this far below the 28-day average
RESTING_HR_RISE_BPM = 3        # latest resting HR this far above the 28-day average
BODY_BATTERY_DROP = 25         # wake-up body battery this far below the 28-day average
FLAG_RULES = (
    "Simple rules on Garmin's own numbers, not a score or medical advice: HRV below Garmin's range; "
    "7-day HRV average 20% or more under the 28-day average; resting HR 3+ bpm over its 28-day average; "
    "last night under 6 h; 3+ nights under 6.5 h in the last 7; wake-up body battery 25+ under its 28-day average."
)

RECOVERY_COLUMNS = """
    calendar_date, sleep_seconds, sleep_score, hrv_last_night_avg, hrv_status, hrv_balanced_low,
    hrv_balanced_upper, resting_hr_bpm, body_battery_at_wake, avg_stress
"""


def mean(values, places=1):
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), places) if present else None


def recovery_context(connection, local_today):
    """Sleep, HRV, resting heart rate, body battery and stress: latest value plus 7 and 28 day averages.

    Everything is Garmin's stored value. A day Garmin gave nothing for is missing (null), never zero.
    Stress is a daily average that is still building today, so it only counts completed days.
    """
    first = (local_today - timedelta(days=27)).isoformat()
    rows = [dict(r) for r in connection.execute(
        f"SELECT {RECOVERY_COLUMNS} FROM wellness_daily WHERE calendar_date >= ? AND calendar_date <= ? ORDER BY calendar_date",
        (first, local_today.isoformat()),
    )]
    if not rows:
        return {"available": False, "reason": "No wellness data is stored for the last 28 days."}

    today_text = local_today.isoformat()
    seven_from = (local_today - timedelta(days=6)).isoformat()
    last7 = [r for r in rows if r["calendar_date"] >= seven_from]
    latest = rows[-1]
    complete = [r for r in rows if r["calendar_date"] < today_text]       # stress only counts finished days
    complete7 = [r for r in complete if r["calendar_date"] >= seven_from]

    def hours(r):
        return None if r["sleep_seconds"] is None else r["sleep_seconds"] / 3600

    sleep7, sleep28 = [hours(r) for r in last7], [hours(r) for r in rows]
    short_nights = sum(1 for h in sleep7 if h is not None and h < SHORT_SLEEP_NIGHT_HOURS)
    hrv_low, hrv_high = latest["hrv_balanced_low"], latest["hrv_balanced_upper"]
    last_complete = complete[-1] if complete else None

    block = {
        "data_through": latest["calendar_date"],
        "sleep": {
            "last_night_hours": None if hours(latest) is None else round(hours(latest), 2),
            "last_night_score": latest["sleep_score"],
            "avg_hours_7d": mean(sleep7, 2),
            "avg_hours_28d": mean(sleep28, 2),
            "avg_score_7d": mean([r["sleep_score"] for r in last7]),
            "avg_score_28d": mean([r["sleep_score"] for r in rows]),
            "nights_under_6_5h_of_last_7": short_nights,
        },
        "hrv": {
            "last_night_ms": latest["hrv_last_night_avg"],
            "avg_7d_ms": mean([r["hrv_last_night_avg"] for r in last7]),
            "avg_28d_ms": mean([r["hrv_last_night_avg"] for r in rows]),
            "garmin_balanced_range_ms": None if hrv_low is None or hrv_high is None else [hrv_low, hrv_high],
            "garmin_status": latest["hrv_status"],
        },
        "resting_hr_bpm": {
            "latest": latest["resting_hr_bpm"],
            "avg_7d": mean([r["resting_hr_bpm"] for r in last7]),
            "avg_28d": mean([r["resting_hr_bpm"] for r in rows]),
        },
        "body_battery_at_wake": {
            "latest": latest["body_battery_at_wake"],
            "avg_7d": mean([r["body_battery_at_wake"] for r in last7]),
            "avg_28d": mean([r["body_battery_at_wake"] for r in rows]),
        },
        "stress_daily_avg_full_days": {
            "latest": None if last_complete is None else last_complete["avg_stress"],
            "latest_date": None if last_complete is None else last_complete["calendar_date"],
            "avg_7d": mean([r["avg_stress"] for r in complete7]),
            "avg_28d": mean([r["avg_stress"] for r in complete]),
        },
    }

    def count(window, key):
        return sum(1 for r in window if r[key] is not None)

    block["days_with_data"] = {
        "last_7_days": {"sleep": count(last7, "sleep_seconds"), "hrv": count(last7, "hrv_last_night_avg"),
                        "resting_hr": count(last7, "resting_hr_bpm"), "body_battery": count(last7, "body_battery_at_wake"),
                        "stress": count(complete7, "avg_stress")},
        "last_28_days": {"sleep": count(rows, "sleep_seconds"), "hrv": count(rows, "hrv_last_night_avg"),
                         "resting_hr": count(rows, "resting_hr_bpm"), "body_battery": count(rows, "body_battery_at_wake"),
                         "stress": count(complete, "avg_stress")},
    }

    flags = []
    hrv = block["hrv"]
    if hrv["last_night_ms"] is not None and hrv_low is not None and hrv["last_night_ms"] < hrv_low:
        flags.append({"flag": "hrv_below_garmin_range", "detail": f"{hrv['last_night_ms']} ms vs Garmin range {hrv_low}-{hrv_high}"})
    if hrv["avg_7d_ms"] and hrv["avg_28d_ms"] and hrv["avg_7d_ms"] <= hrv["avg_28d_ms"] * (1 - HRV_TREND_DROP):
        flags.append({"flag": "hrv_trending_down", "detail": f"7-day {hrv['avg_7d_ms']} vs 28-day {hrv['avg_28d_ms']} ms"})
    rhr = block["resting_hr_bpm"]
    if rhr["latest"] is not None and rhr["avg_28d"] is not None and rhr["latest"] >= rhr["avg_28d"] + RESTING_HR_RISE_BPM:
        flags.append({"flag": "resting_hr_elevated", "detail": f"{rhr['latest']} bpm vs 28-day average {rhr['avg_28d']}"})
    last_hours = hours(latest)
    if last_hours is not None and last_hours < VERY_SHORT_SLEEP_HOURS:
        flags.append({"flag": "short_sleep_last_night", "detail": f"{round(last_hours, 1)} h"})
    if short_nights >= 3:
        flags.append({"flag": "several_short_nights", "detail": f"{short_nights} of the last 7 nights under {SHORT_SLEEP_NIGHT_HOURS} h"})
    battery = block["body_battery_at_wake"]
    if battery["latest"] is not None and battery["avg_28d"] is not None and battery["latest"] <= battery["avg_28d"] - BODY_BATTERY_DROP:
        flags.append({"flag": "low_body_battery_at_wake", "detail": f"{battery['latest']} vs 28-day average {battery['avg_28d']}"})
    block["flags"] = flags
    block["flag_rules"] = FLAG_RULES

    notes = []
    if latest["calendar_date"] != today_text:
        notes.append(f"No recovery data for today yet; the latest is {latest['calendar_date']}.")
    for label, value in (("Last night's sleep", latest["sleep_seconds"]), ("Last night's HRV", latest["hrv_last_night_avg"]),
                         ("Today's resting heart rate", latest["resting_hr_bpm"]), ("Wake-up body battery", latest["body_battery_at_wake"])):
        if value is None:
            notes.append(f"{label} is missing from Garmin (not worn, not synced, or not recorded); it is not zero.")
    if not flags:
        notes.append("No flag rule triggered. That does not guarantee good recovery.")
    block["notes"] = notes
    return block


# ---------- the tool's output ----------

ACTIVITY_COLUMNS = """
    garmin_activity_id, local_date, start_time_local, started_at_utc, activity_type, sub_sport, garmin_type_key,
    activity_name, distance_m, duration_seconds, avg_heart_rate_bpm, max_heart_rate_bpm, total_ascent_m,
    aerobic_training_effect, anaerobic_training_effect, training_load, hr_zone1_seconds, hr_zone2_seconds,
    hr_zone3_seconds, hr_zone4_seconds, hr_zone5_seconds, garmin_adjusted, lap_distance_adjusted
"""


def open_read_only(db_path):
    """The only way this module touches the database: read-only, enforced by SQLite itself."""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def build_context(connection, now, local_today, status, recent_limit=DEFAULT_RECENT, local_timezone="local"):
    """The `get_training_context` result. now is a UTC datetime; local_today is the athlete's current local date."""
    recent_limit = max(1, min(int(recent_limit), MAX_RECENT))
    first_needed = min(local_today - timedelta(days=max(WINDOW_DAYS) - 1), monday_of(local_today) - timedelta(days=7 * (WEEKS_SHOWN - 1)))
    rows = [dict(r) for r in connection.execute(
        f"SELECT {ACTIVITY_COLUMNS} FROM activities WHERE local_date IS NOT NULL AND local_date >= ? AND local_date <= ?",
        (first_needed.isoformat(), local_today.isoformat()),
    )]
    undated = connection.execute("SELECT COUNT(*) FROM activities WHERE local_date IS NULL").fetchone()[0]
    recent = [dict(r) for r in connection.execute(
        f"SELECT {ACTIVITY_COLUMNS} FROM activities ORDER BY started_at_utc DESC LIMIT ?", (recent_limit,)
    )]
    recent_strength = [dict(r) for r in connection.execute(
        f"SELECT {ACTIVITY_COLUMNS} FROM activities WHERE activity_type = 'training' AND sub_sport = 'strength_training' ORDER BY started_at_utc DESC LIMIT 5"
    )]
    latest_row = recent[0] if recent else None

    windows = {}
    for days in WINDOW_DAYS:
        first_day = (local_today - timedelta(days=days - 1)).isoformat()
        windows[f"last_{days}_days"] = window_summary(rows, first_day, local_today.isoformat())

    seven, twenty_eight = windows["last_7_days"]["running"]["miles"], windows["last_28_days"]["running"]["miles"]
    ratio = round(seven / (twenty_eight / 4), 2) if twenty_eight else None

    missing = [
        "Quality sessions (intervals, threshold, tempo) are not classified yet: lap intensity is not parsed, so none are reported.",
        "Garmin's training readiness, training status and recovery time are not available from the Garmin Personal API.",
    ]
    if undated:
        missing.append(f"{undated} activities have no local date and are excluded from the windows.")
    for name, window in windows.items():
        if window["running"]["runs_without_heart_rate_zones"]:
            missing.append(f"{name}: {window['running']['runs_without_heart_rate_zones']} runs have no heart-rate-zone data.")

    return {
        "as_of": {"local_date": local_today.isoformat(), "timezone": local_timezone, "generated_at_utc": now.replace(microsecond=0).isoformat()},
        "units": UNITS,
        "data_notes": "Dates are each activity's own local date. 'miles' and 'minutes' under running count runs only (treadmill included, see flags). Distances follow Garmin.",
        "freshness": freshness(status, latest_row, now),
        "training_load": {
            "windows": windows,
            "last_7_days_miles_vs_28_day_weekly_average": ratio,
            "ratio_explained": "miles in the last 7 days divided by the 28-day weekly average (28-day miles / 4). Null when there were no runs in 28 days.",
            "today_is_partial": True,
        },
        "weekly_mileage": weekly_breakdown(rows, local_today),
        "recent_long_runs": longest_run_each_week(rows, local_today),
        "quality_sessions": {"available": False, "reason": missing[0]},
        "recovery": recovery_context(connection, local_today),
        "recent_strength_sessions": [activity_summary(r) for r in recent_strength],
        "recent_activities": [activity_summary(r) for r in recent],
        "missing": missing,
    }
