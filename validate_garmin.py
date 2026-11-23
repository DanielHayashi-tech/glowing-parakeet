#!/usr/bin/env python
"""Validate the local database against Garmin (read-only). Exit code 0 = every check passed.

    python validate_garmin.py                 # full validation, writes a report
    python validate_garmin.py --no-wellness-sample   # skip the live wellness spot-check

What it checks, against Garmin's own data fetched live:
  completeness   every Garmin activity is imported, or documented as having no original file
  uniqueness     Garmin activity IDs are unique in the database
  time           start instant, local start, local calendar date and UTC offset match Garmin
  values         distance within 0.5%, duration within 1 s, heart rate within 1 bpm
  weekly miles   Monday-Sunday running mileage for the last 8 weeks, by Garmin's local dates
  laps           lap-distance disagreement is explained (treadmill calibration) or a failure
  metrics        Garmin's training effect / load / HR-zone time are stored
  wellness       every day since the first data is stored or recorded as empty; sampled days
                 match a fresh Garmin response
  spot checks    a long run, an interval-like run, a treadmill run, a strength session and an
                 activity recorded while traveling, compared with Garmin's activity detail

Garmin Connect is not scraped. The comparison is with what Garmin's servers return (the list and
the per-activity detail), which is what Connect itself displays.
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

import sync_garmin_api as garmin  # noqa: E402
import sync_garmin_wellness as wellness  # noqa: E402

DB_PATH = "data_hub.db"
REPORT_DIR = Path("docs/reports")
DETAIL_DIR = Path("temp/validation")
RUNNING_KEYS = {"running", "treadmill_running", "trail_running", "track_running", "virtual_run", "indoor_running"}
DISTANCE_TOLERANCE = 0.005   # 0.5%
DURATION_TOLERANCE_S = 1.0
HR_TOLERANCE_BPM = 1.0
WEEKLY_MILE_TOLERANCE = 0.05
WEEKS_TO_CHECK = 8
STALE_AFTER_HOURS = 3
METERS_PER_MILE = 1609.344


# ---------- pure helpers (unit tested) ----------

def monday_of(day):
    return day - timedelta(days=day.weekday())


def garmin_offset_minutes(item):
    local = datetime.strptime(item["startTimeLocal"], "%Y-%m-%d %H:%M:%S")
    gmt = datetime.strptime(item["startTimeGMT"], "%Y-%m-%d %H:%M:%S")
    return int((local - gmt).total_seconds() // 60)


def compare_activity(row, item):
    """Names of fields where a database row disagrees with Garmin's list item. Empty = match.

    row is a dict of database columns; item is Garmin's list entry for the same activity.
    """
    problems = []
    start_utc = datetime.fromisoformat(row["started_at_utc"])
    garmin_utc = datetime.strptime(item["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if abs((start_utc - garmin_utc).total_seconds()) > 2:
        problems.append("start_time")
    if row.get("local_date") != item["startTimeLocal"][:10]:
        problems.append("local_date")
    if row.get("start_time_local") != item["startTimeLocal"].replace(" ", "T"):
        problems.append("start_time_local")
    if row.get("utc_offset_minutes") != garmin_offset_minutes(item):
        problems.append("utc_offset")
    garmin_distance = item.get("distance")
    if garmin_distance and row.get("distance_m") is not None:
        if abs(row["distance_m"] - garmin_distance) > DISTANCE_TOLERANCE * garmin_distance:
            problems.append("distance")
    if item.get("duration") is not None and row.get("duration_seconds") is not None:
        if abs(row["duration_seconds"] - item["duration"]) > DURATION_TOLERANCE_S:
            problems.append("duration")
    for column, key, name in (("avg_heart_rate_bpm", "averageHR", "avg_hr"), ("max_heart_rate_bpm", "maxHR", "max_hr")):
        if item.get(key) is not None and row.get(column) is not None:
            if abs(row[column] - item[key]) > HR_TOLERANCE_BPM:
                problems.append(name)
    return problems


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


def pick_spot_checks(rows, home_offsets=(-300, -360, -420, -240)):
    """Choose representative activities. rows: dicts with the columns used below.

    Returns {label: row}. A label is omitted if no activity qualifies.
    """
    runs = [r for r in rows if r["activity_type"] == "running" and r.get("sub_sport") != "treadmill"]
    picks = {}
    if runs:
        picks["long run"] = max(runs, key=lambda r: r["distance_m"] or 0)
    spread = [r for r in runs if r.get("lap_pace_spread") is not None]
    if spread:
        picks["interval-like run (derived from lap pace variation)"] = max(spread, key=lambda r: r["lap_pace_spread"])
    treadmill = [r for r in rows if r["activity_type"] == "running" and r.get("sub_sport") == "treadmill"]
    if treadmill:
        picks["treadmill run"] = max(treadmill, key=lambda r: r["distance_m"] or 0)
    strength = [r for r in rows if r["activity_type"] == "training"]
    if strength:
        picks["strength session"] = max(strength, key=lambda r: r["duration_seconds"] or 0)
    abroad = [r for r in rows if r.get("utc_offset_minutes") not in home_offsets and r.get("utc_offset_minutes") is not None]
    if abroad:
        picks["recorded while traveling"] = max(abroad, key=lambda r: r["distance_m"] or 0)
    return picks


# ---------- checks ----------

class Report:
    def __init__(self):
        self.checks = []   # (name, status, summary, details)

    def add(self, name, ok, summary, details=None, warn=False):
        status = "pass" if ok else ("warn" if warn else "FAIL")
        self.checks.append((name, status, summary, details or []))

    @property
    def failed(self):
        return [c for c in self.checks if c[1] == "FAIL"]


def load_rows(connection):
    connection.row_factory = sqlite3.Row
    rows = [dict(r) for r in connection.execute("SELECT * FROM activities")]
    lap_rows = connection.execute("SELECT activity_id, avg_speed_mps FROM laps WHERE avg_speed_mps > 0").fetchall()
    by_activity = defaultdict(list)
    for activity_id, speed in lap_rows:
        by_activity[activity_id].append(speed)
    for row in rows:
        speeds = by_activity.get(row["id"], [])
        row["lap_pace_spread"] = (max(speeds) - min(speeds)) / (sum(speeds) / len(speeds)) if len(speeds) >= 5 else None
    return rows


def fetch_all_garmin(client):
    items, start = [], 0
    while True:
        page = client.list_activities(start, 50)
        if not page:
            break
        items += page
        start += 50
        if len(page) < 50:
            break
    return items


def check_activities(report, connection, rows, items):
    by_id = {i["activityId"]: i for i in items}
    mine = {r["garmin_activity_id"]: r for r in rows if r["garmin_activity_id"]}
    documented = {
        r[0]: r[1]
        for r in connection.execute(
            "SELECT garmin_activity_id, fit_status FROM garmin_activity_raw WHERE fit_status IN ('no_original', 'invalid')"
        )
    }
    missing = sorted(set(by_id) - set(mine) - set(documented))
    report.add("Completeness", not missing,
               f"{len(mine)} of {len(by_id)} Garmin activities imported; {len(documented)} documented as unavailable; {len(missing)} unexplained missing",
               [str(i) for i in missing[:20]])
    extra = sorted(set(mine) - set(by_id))
    report.add("No activities Garmin does not have", not extra, f"{len(extra)} in database but not in Garmin's list", [str(i) for i in extra[:20]], warn=True)

    null_ids = sum(1 for r in rows if not r["garmin_activity_id"])
    ids = [r["garmin_activity_id"] for r in rows if r["garmin_activity_id"]]
    report.add("Garmin activity IDs unique", len(ids) == len(set(ids)) and null_ids == 0,
               f"{len(ids)} IDs, {len(set(ids))} distinct, {null_ids} rows without an ID")

    problems = defaultdict(list)
    for garmin_id, row in mine.items():
        item = by_id.get(garmin_id)
        if item:
            for name in compare_activity(row, item):
                problems[name].append(garmin_id)
    for name, label in (("start_time", "Start instant"), ("local_date", "Local calendar date"), ("start_time_local", "Local start time"),
                        ("utc_offset", "UTC offset"), ("distance", "Distance within 0.5%"), ("duration", "Duration within 1 s"),
                        ("avg_hr", "Average heart rate within 1 bpm"), ("max_hr", "Max heart rate within 1 bpm")):
        bad = problems.get(name, [])
        report.add(label, not bad, f"{len(mine) - len(bad)} of {len(mine)} match Garmin; {len(bad)} differ", [str(i) for i in bad[:20]])

    no_metrics = [g for g, r in mine.items() if r["metrics_fetched_at"] is None]
    report.add("Garmin metrics stored", not no_metrics, f"{len(mine) - len(no_metrics)} of {len(mine)} activities have Garmin's training metrics", [str(i) for i in no_metrics[:20]])
    wrong = [g for g, r in mine.items() if by_id.get(g) and by_id[g].get("aerobicTrainingEffect") is not None
             and (r["aerobic_training_effect"] is None or abs(r["aerobic_training_effect"] - by_id[g]["aerobicTrainingEffect"]) > 0.05)]
    report.add("Training effect matches Garmin", not wrong, f"{len(wrong)} differ", [str(i) for i in wrong[:20]])
    bad_cadence = [g for g, r in mine.items() if (r["avg_cadence_spm"] or 0) > 300]
    report.add("No invalid cadence values (the 510 sentinel)", not bad_cadence, f"{len(bad_cadence)} activities with cadence above 300", [str(i) for i in bad_cadence[:20]])

    unexplained = [g for g, r in mine.items() if r["lap_distance_adjusted"] == 1 and r.get("sub_sport") != "treadmill"]
    flagged = [g for g, r in mine.items() if r["lap_distance_adjusted"] == 1]
    report.add("Lap-distance discrepancies explained", not unexplained,
               f"{len(flagged)} activities have laps differing from the session distance by more than 1%; {len(flagged) - len(unexplained)} are treadmill runs (distance calibration), {len(unexplained)} unexplained",
               [str(i) for i in unexplained[:20]])
    return by_id, mine


def check_weekly_miles(report, rows, items, today):
    garmin_entries = [(i["startTimeLocal"][:10], i["distance"]) for i in items if i["activityType"]["typeKey"] in RUNNING_KEYS]
    db_entries = [(r["local_date"], r["distance_m"]) for r in rows if r["activity_type"] == "running" and r["local_date"]]
    garmin_weeks = weekly_running_miles(garmin_entries, WEEKS_TO_CHECK, today)
    db_weeks = weekly_running_miles(db_entries, WEEKS_TO_CHECK, today)
    bad = [(m.isoformat(), round(db_weeks[m], 2), round(garmin_weeks[m], 2)) for m in garmin_weeks if abs(db_weeks[m] - garmin_weeks[m]) > WEEKLY_MILE_TOLERANCE]
    lines = [f"week of {m.isoformat()}: database {db_weeks[m]:.2f} mi, Garmin {garmin_weeks[m]:.2f} mi" for m in sorted(garmin_weeks, reverse=True)]
    report.add("Weekly running mileage (last 8 Monday-Sunday weeks)", not bad,
               f"{WEEKS_TO_CHECK - len(bad)} of {WEEKS_TO_CHECK} weeks agree within {WEEKLY_MILE_TOLERANCE} mi", lines)


def check_wellness(report, connection, client, sample, today):
    first = connection.execute("SELECT MIN(calendar_date) FROM wellness_fetch_log WHERE status = 'ok'").fetchone()[0] \
        or connection.execute("SELECT MIN(calendar_date) FROM wellness_daily").fetchone()[0]
    if not first:
        report.add("Wellness coverage", False, "no wellness data stored")
        return
    start = date.fromisoformat(first)
    settled = {r[0] for r in connection.execute("SELECT calendar_date FROM wellness_fetch_log WHERE status IN ('ok','empty')")}
    settled |= {r[0] for r in connection.execute("SELECT calendar_date FROM wellness_daily")}
    unsettled = [(start + timedelta(days=k)).isoformat() for k in range((today - start).days + 1)
                 if (start + timedelta(days=k)).isoformat() not in settled]
    stored = connection.execute("SELECT COUNT(*) FROM wellness_daily").fetchone()[0]
    empty = connection.execute("SELECT COUNT(*) FROM wellness_fetch_log WHERE status = 'empty'").fetchone()[0]
    errors = connection.execute("SELECT COUNT(*) FROM wellness_fetch_log WHERE status = 'error'").fetchone()[0]
    report.add("Wellness coverage", not unsettled and not errors,
               f"{first} to {today.isoformat()}: {stored} days stored, {empty} recorded as no data, {len(unsettled)} unaccounted for, {errors} errored",
               unsettled[:20])
    if not sample:
        return
    wellness.REQUEST_DELAY_SECONDS = 0.2
    athlete_id = connection.execute("SELECT id FROM athletes ORDER BY id LIMIT 1").fetchone()[0]
    ages = [4, 7, 30, 90, 180, 365]   # skip the last 3 days: they are still changing
    mismatches, checked = [], 0
    for age in ages:
        day = (today - timedelta(days=age)).isoformat()
        row = connection.execute("SELECT * FROM wellness_daily WHERE athlete_id = ? AND calendar_date = ?", (athlete_id, day)).fetchone()
        if row is None:
            continue
        fresh = wellness.normalize(wellness.fetch_day(client, day))
        checked += 1
        for key, value in fresh.items():
            stored_value = row[key]
            same = (value is None and stored_value is None) or (
                value is not None and stored_value is not None and abs(float(value) - float(stored_value)) < 1e-6) or value == stored_value
            if not same:
                mismatches.append(f"{day} {key}: stored {stored_value} vs Garmin {value}")
    report.add("Wellness values match a fresh Garmin response", not mismatches,
               f"{checked} sampled days re-fetched from Garmin; {len(mismatches)} field differences", mismatches[:20])


def check_spot_checks(report, client, rows, by_id):
    picks = pick_spot_checks(rows)
    for label in ("long run", "interval-like run (derived from lap pace variation)", "treadmill run", "strength session", "recorded while traveling"):
        row = picks.get(label)
        if row is None:
            report.add(f"Spot check: {label}", False, "no matching activity found to check", warn=True)
            continue
        body = client._request(f"/activity-service/activity/{row['garmin_activity_id']}", "application/json")
        detail = json.loads(body)["summaryDTO"] if body else {}
        diffs = []
        def near(name, mine, theirs, tolerance):
            if theirs is not None and mine is not None and abs(mine - theirs) > tolerance:
                diffs.append(f"{name}: database {mine:.2f} vs Garmin detail {theirs:.2f}")
        near("distance (m)", row["distance_m"], detail.get("distance"), max(1.0, DISTANCE_TOLERANCE * (detail.get("distance") or 0)))
        near("duration (s)", row["duration_seconds"], detail.get("duration"), DURATION_TOLERANCE_S)
        near("avg HR", row["avg_heart_rate_bpm"], detail.get("averageHR"), HR_TOLERANCE_BPM)
        near("max HR", row["max_heart_rate_bpm"], detail.get("maxHR"), HR_TOLERANCE_BPM)
        near("calories", row["calories_kcal"], detail.get("calories"), 2)
        near("elevation gain (m)", row["total_ascent_m"], detail.get("elevationGain"), 5)
        if detail.get("startTimeLocal") and row["start_time_local"] != detail["startTimeLocal"][:19]:
            diffs.append(f"local start: database {row['start_time_local']} vs Garmin detail {detail['startTimeLocal'][:19]}")
        list_item = by_id.get(row["garmin_activity_id"], {})
        lap_count = list_item.get("lapCount")
        report_laps = f", laps Garmin {lap_count}" if lap_count is not None else ""
        report.add(f"Spot check: {label}", not diffs,
                   f"activity {row['garmin_activity_id']} ({row['garmin_type_key'] or row['activity_type']}) compared with Garmin's activity detail{report_laps}",
                   diffs)


# ---------- output ----------

def write_reports(report, counts, today):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = today.isoformat()
    verdict = "PASS" if not report.failed else f"FAIL ({len(report.failed)} checks)"
    lines = [f"# Garmin validation {stamp}", "", f"Result: **{verdict}**", "",
             f"Activities in database: {counts['db']}, in Garmin: {counts['garmin']}.", "",
             "Compared live against Garmin's activity list and per-activity detail (Garmin Connect itself is not scraped).",
             "Per-activity detail for any failures is in `temp/validation/` (not committed).", ""]
    for name, status, summary, details in report.checks:
        lines.append(f"- **{status}** {name}: {summary}")
        if status != "pass" and details:
            lines.extend(f"    - {d}" for d in details[:10])
    weekly = [c for c in report.checks if c[0].startswith("Weekly running")]
    if weekly:
        lines += ["", "## Weekly running mileage", ""] + [f"- {d}" for d in weekly[0][3]]
    (REPORT_DIR / f"garmin-validation-{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    full = [{"check": n, "status": s, "summary": m, "details": d} for n, s, m, d in report.checks]
    (DETAIL_DIR / f"garmin-validation-{stamp}.json").write_text(json.dumps(full, indent=2), encoding="utf-8")
    return REPORT_DIR / f"garmin-validation-{stamp}.md"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--no-wellness-sample", action="store_true", help="Skip re-fetching sample wellness days.")
    args = parser.parse_args()
    garmin.load_dotenv()
    client = garmin.GarminClient(os.environ.get("GARMIN_PERSONAL_API_KEY", "").strip())
    connection = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    today = date.today()
    report = Report()

    items = fetch_all_garmin(client)
    rows = load_rows(connection)
    by_id, _mine = check_activities(report, connection, rows, items)
    check_weekly_miles(report, rows, items, today)
    check_wellness(report, connection, client, not args.no_wellness_sample, today)
    check_spot_checks(report, client, rows, by_id)

    try:
        status = json.loads(Path("temp/last_sync.json").read_text(encoding="utf-8"))
        last = status.get("last_success_at")
        hours = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600 if last else None
        report.add("Sync is current", hours is not None and hours <= STALE_AFTER_HOURS,
                   f"last successful sync {hours:.1f} hours ago" if hours is not None else "no successful sync recorded", warn=True)
    except (OSError, ValueError):
        report.add("Sync is current", False, "no sync status file", warn=True)

    path = write_reports(report, {"db": len(rows), "garmin": len(items)}, today)
    for name, status, summary, _details in report.checks:
        print(f"[{status:4}] {name}: {summary}")
    print(f"\nReport: {path}")
    return 0 if not report.failed else 1


if __name__ == "__main__":
    sys.exit(main())
