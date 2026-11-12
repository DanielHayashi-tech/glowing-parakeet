#!/usr/bin/env python
"""Pull daily wellness data (sleep, HRV, heart rate, summary) from the Garmin Personal API.

Writes two things per day: the raw responses (wellness_raw, so more fields can be
extracted later without refetching) and a normalized row (wellness_daily).

Reuses the client from sync_garmin_api.py, so auth, retries and the 24h token
handling are the same. See docs/garmin-personal-api-notes.md.
"""

import json
import os
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import sync_garmin_api as garmin

ENDPOINTS = {
    "summary": "/usersummary-service/usersummary/daily?calendarDate={day}",
    "sleep": "/sleep-service/sleep/dailySleep?date={day}",
    "hrv": "/hrv-service/hrv/{day}",
    "heart_rate": "/wellness-service/wellness/dailyHeartRate?date={day}",
}
REQUEST_DELAY_SECONDS = 0.4
BACKFILL_DAYS = 30
# Today's numbers keep changing and last night's sleep lands in the morning, so
# every run re-reads the most recent days.
REFRESH_DAYS = 3
SCHEMA_PATH = Path("schema.sql")


def number(value, kind=float):
    """A number, or None for missing / non-numeric (Garmin uses null and sentinels)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return kind(value)


def millis_to_iso(value):
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(microsecond=0).isoformat()


def normalize(payloads):
    """Flatten the four raw responses into one wellness_daily row (columns only)."""
    summary = payloads.get("summary") or {}
    sleep = payloads.get("sleep") or {}
    hrv = payloads.get("hrv") or {}
    heart_rate = payloads.get("heart_rate") or {}
    hrv_summary = hrv.get("hrvSummary") or {}
    hrv_baseline = hrv_summary.get("baseline") or {}
    sleep_scores = sleep.get("sleepScores") or {}
    overall = sleep_scores.get("overall") or {}

    resting = number(summary.get("restingHeartRate"), int)
    if resting is None:
        resting = number(heart_rate.get("restingHeartRate"), int)

    return {
        "steps": number(summary.get("totalSteps"), int),
        "step_goal": number(summary.get("dailyStepGoal"), int),
        "active_kcal": number(summary.get("activeKilocalories")),
        "moderate_intensity_minutes": number(summary.get("moderateIntensityMinutes"), int),
        "vigorous_intensity_minutes": number(summary.get("vigorousIntensityMinutes"), int),
        "resting_hr_bpm": resting,
        "resting_hr_7d_avg_bpm": number(summary.get("lastSevenDaysAvgRestingHeartRate"), int),
        "min_hr_bpm": number(summary.get("minHeartRate"), int),
        "max_hr_bpm": number(summary.get("maxHeartRate"), int),
        "avg_stress": number(summary.get("averageStressLevel"), int),
        "body_battery_high": number(summary.get("bodyBatteryHighestValue"), int),
        "body_battery_low": number(summary.get("bodyBatteryLowestValue"), int),
        "body_battery_at_wake": number(summary.get("bodyBatteryAtWakeTime"), int),
        "sleep_seconds": number(sleep.get("sleepTimeSeconds"), int),
        "deep_sleep_seconds": number(sleep.get("deepSleepSeconds"), int),
        "light_sleep_seconds": number(sleep.get("lightSleepSeconds"), int),
        "rem_sleep_seconds": number(sleep.get("remSleepSeconds"), int),
        "awake_seconds": number(sleep.get("awakeSleepSeconds"), int),
        "sleep_score": number(overall.get("value"), int),
        "sleep_avg_hr_bpm": number(sleep.get("avgHeartRate")),
        "sleep_avg_spo2": number(sleep.get("averageSpO2Value")),
        "sleep_avg_respiration": number(sleep.get("averageRespirationValue")),
        "sleep_start_utc": millis_to_iso(sleep.get("sleepStartTimestampGMT")),
        "sleep_end_utc": millis_to_iso(sleep.get("sleepEndTimestampGMT")),
        "hrv_last_night_avg": number(hrv_summary.get("lastNightAvg"), int),
        "hrv_weekly_avg": number(hrv_summary.get("weeklyAvg"), int),
        "hrv_status": hrv_summary.get("status") if isinstance(hrv_summary.get("status"), str) else None,
        "hrv_balanced_low": number(hrv_baseline.get("balancedLow"), int),
        "hrv_balanced_upper": number(hrv_baseline.get("balancedUpper"), int),
    }


def ensure_athlete(connection, display_name, timezone_name):
    row = connection.execute(
        "SELECT id FROM athletes WHERE display_name = ? ORDER BY id LIMIT 1", (display_name,)
    ).fetchone()
    if row:
        return row[0]
    cursor = connection.execute(
        "INSERT INTO athletes(display_name, timezone) VALUES(?, ?)", (display_name, timezone_name)
    )
    return cursor.lastrowid


def days_to_fetch(connection, athlete_id, today, backfill_days=BACKFILL_DAYS):
    """Oldest day first. Resumes a couple of days before the newest stored day."""
    newest = connection.execute(
        "SELECT MAX(calendar_date) FROM wellness_daily WHERE athlete_id = ?", (athlete_id,)
    ).fetchone()[0]
    earliest_allowed = today - timedelta(days=backfill_days)
    if newest:
        start = max(date.fromisoformat(newest) - timedelta(days=REFRESH_DAYS - 1), earliest_allowed)
    else:
        start = earliest_allowed
    start = min(start, today - timedelta(days=REFRESH_DAYS - 1))
    return [start + timedelta(days=offset) for offset in range((today - start).days + 1)]


def store_day(connection, athlete_id, day_iso, payloads):
    for kind, payload in payloads.items():
        if payload is not None:
            connection.execute(
                """
                INSERT INTO wellness_raw(athlete_id, calendar_date, kind, payload, fetched_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(athlete_id, calendar_date, kind)
                DO UPDATE SET payload = excluded.payload, fetched_at = CURRENT_TIMESTAMP
                """,
                (athlete_id, day_iso, kind, json.dumps(payload)),
            )
    row = normalize(payloads)
    columns = list(row)
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{name} = excluded.{name}" for name in columns)
    connection.execute(
        f"""
        INSERT INTO wellness_daily(athlete_id, calendar_date, {", ".join(columns)}, fetched_at)
        VALUES (?, ?, {placeholders}, CURRENT_TIMESTAMP)
        ON CONFLICT(athlete_id, calendar_date)
        DO UPDATE SET {updates}, fetched_at = CURRENT_TIMESTAMP
        """,
        [athlete_id, day_iso, *row.values()],
    )


def fetch_day(client, day_iso):
    payloads = {}
    for kind, template in ENDPOINTS.items():
        body = client._request(template.format(day=day_iso), "application/json")
        payloads[kind] = json.loads(body) if body else None
        time.sleep(REQUEST_DELAY_SECONDS)
    return payloads


def run(db_path, athlete_name, timezone_name, log, backfill_days=BACKFILL_DAYS, client=None, today=None):
    """Fetch and store recent days. Returns a summary dict; raises GarminError only for auth failures."""
    client = client or garmin.GarminClient(os.environ.get("GARMIN_PERSONAL_API_KEY", "").strip(), log=log)
    today = today or date.today()
    summary = {"days_checked": 0, "days_stored": 0, "days_failed": 0, "first_error": None}

    connection = sqlite3.connect(db_path)
    try:
        # Idempotent; makes sure the wellness tables exist on databases from before migration 0004.
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        athlete_id = ensure_athlete(connection, athlete_name, timezone_name)
        connection.commit()

        for day in days_to_fetch(connection, athlete_id, today, backfill_days):
            day_iso = day.isoformat()
            summary["days_checked"] += 1
            try:
                payloads = fetch_day(client, day_iso)
            except garmin.GarminError as error:
                # One bad day should not lose the rest, but remember why.
                summary["days_failed"] += 1
                summary["first_error"] = summary["first_error"] or str(error)
                log(f"wellness {day_iso}: {error}")
                continue
            if all(payload is None for payload in payloads.values()):
                continue  # Garmin has nothing for this day yet (for example today before sync).
            store_day(connection, athlete_id, day_iso, payloads)
            connection.commit()
            summary["days_stored"] += 1
    finally:
        connection.close()
    return summary
