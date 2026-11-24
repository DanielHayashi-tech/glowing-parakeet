import sqlite3
import unittest
from datetime import date, datetime, timedelta, timezone

from tests import _path  # noqa: F401
import db_upgrade
import training_context as tc

TODAY = date(2026, 11, 25)                       # a Wednesday
NOW = datetime(2026, 11, 25, 18, 0, tzinfo=timezone.utc)
MILE = tc.METERS_PER_MILE


def database():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    db_upgrade.apply_schema(connection, str(_path.ROOT / "schema.sql"))
    connection.execute("INSERT INTO athletes(id, display_name) VALUES (1, 'a')")
    return connection


def add(connection, day, kind="running", sub="generic", miles=0.0, minutes=0.0, hr=None, load=None, zones=None, **extra):
    row = {"athlete_id": 1, "activity_type": kind, "sport": kind, "sub_sport": sub, "garmin_type_key": kind,
           "local_date": day, "start_time_local": f"{day}T07:00:00", "started_at_utc": f"{day}T12:00:00+00:00",
           "distance_m": miles * MILE, "duration_seconds": minutes * 60, "avg_heart_rate_bpm": hr,
           "training_load": load, "garmin_activity_id": add.counter}
    add.counter += 1
    if zones:
        for number, seconds in enumerate(zones, start=1):
            row[f"hr_zone{number}_seconds"] = seconds
    row.update(extra)
    connection.execute(f"INSERT INTO activities({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


add.counter = 1000


def context(connection, status=None, **kwargs):
    return tc.build_context(connection, NOW, TODAY, status, **kwargs)


def fresh_status(hours=1, ok=True):
    return {"last_success_at": (NOW - timedelta(hours=hours)).isoformat(), "finished_at": NOW.isoformat(), "ok": ok, "message": "ok"}


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.db = database()
        add(self.db, "2026-11-25", miles=5, minutes=45, hr=150, load=60, zones=[0, 1800, 900, 0, 0])   # today
        add(self.db, "2026-11-23", miles=10, minutes=90, hr=140, load=100, zones=[0, 5400, 0, 0, 0])    # Mon, long run
        add(self.db, "2026-11-22", miles=3, minutes=30, hr=135, load=30)                                  # Sunday: last week, still inside 7 days, no zones
        add(self.db, "2026-11-19", kind="training", sub="strength_training", minutes=40, load=20)       # first day of the 7-day window
        add(self.db, "2026-11-12", miles=6, minutes=54, hr=145, load=55, zones=[0, 3240, 0, 0, 0])       # 13 days ago: in 14d, not 7d
        add(self.db, "2026-10-30", miles=8, minutes=72, hr=142, load=70, zones=[0, 4320, 0, 0, 0])       # 26 days ago: in 28d only
        add(self.db, "2026-11-24", kind="cycling", sub="indoor_cycling", miles=0, minutes=60)            # other activity, no load
        self.result = context(self.db, fresh_status())
        self.windows = self.result["training_load"]["windows"]

    def test_seven_day_window_counts_only_those_days(self):
        w = self.windows["last_7_days"]
        self.assertEqual((w["from"], w["to"], w["days"]), ("2026-11-19", "2026-11-25", 7))
        self.assertEqual(w["running"]["runs"], 3)   # 25th, 23rd and 22nd
        self.assertEqual(w["running"]["miles"], 18.0)
        self.assertEqual(w["running"]["longest_run_miles"], 10.0)

    def test_fourteen_and_twenty_eight_day_windows_widen(self):
        self.assertEqual(self.windows["last_14_days"]["running"]["miles"], 24.0)    # 5+10+3+6
        self.assertEqual(self.windows["last_28_days"]["running"]["miles"], 32.0)    # + 8

    def test_pace_is_total_minutes_over_total_miles(self):
        running = self.windows["last_7_days"]["running"]
        self.assertAlmostEqual(running["avg_pace_min_per_mile"], 9.17, places=2)    # 165 min / 18 mi
        self.assertEqual(running["avg_pace"], "9:10")

    def test_heart_rate_is_weighted_by_duration(self):
        self.assertEqual(self.windows["last_7_days"]["running"]["avg_heart_rate_bpm"], 142)  # (150*45 + 140*90 + 135*30) / 165

    def test_zone_minutes_and_runs_missing_zones(self):
        w = self.windows["last_14_days"]["running"]
        self.assertEqual(w["runs_without_heart_rate_zones"], 1)                      # the 22nd has none
        self.assertEqual(w["heart_rate_zone_minutes"]["zone2"], 30 + 90 + 54)

    def test_strength_other_and_rest_days(self):
        w = self.windows["last_7_days"]
        self.assertEqual(w["strength_sessions"], 1)
        self.assertEqual(w["other_activities"], {"count": 1, "minutes": 60.0})
        self.assertEqual(w["active_days"], 5)                                         # 19, 22, 23, 24, 25
        self.assertEqual(w["rest_days"], 2)

    def test_garmin_load_total_and_gaps(self):
        w = self.windows["last_7_days"]
        self.assertEqual(w["garmin_training_load_total"], 60 + 100 + 30 + 20)
        self.assertEqual(w["activities_without_garmin_training_load"], 1)             # the ride

    def test_acute_ratio_is_explained_and_computed(self):
        # 18 mi in 7 days against a 28-day weekly average of 32 / 4 = 8
        self.assertAlmostEqual(self.result["training_load"]["last_7_days_miles_vs_28_day_weekly_average"], 2.25, places=2)
        self.assertIn("28-day miles / 4", self.result["training_load"]["ratio_explained"])


class WeekTests(unittest.TestCase):
    def test_monday_to_sunday_weeks_and_a_partial_current_week(self):
        db = database()
        add(db, "2026-11-25", miles=5, minutes=45)    # this week (Mon 23)
        add(db, "2026-11-22", miles=3, minutes=30)    # Sunday: belongs to the week of 16 Nov
        add(db, "2026-11-16", miles=7, minutes=60)    # Monday of that week
        weeks = context(db)["weekly_mileage"]
        self.assertEqual(len(weeks), tc.WEEKS_SHOWN)
        self.assertEqual((weeks[0]["week_start"], weeks[0]["is_current_week"], weeks[0]["days_counted"]), ("2026-11-23", True, 3))
        self.assertEqual(weeks[0]["miles"], 5.0)
        self.assertEqual((weeks[1]["week_start"], weeks[1]["is_current_week"], weeks[1]["miles"], weeks[1]["runs"]), ("2026-11-16", False, 10.0, 2))

    def test_the_activitys_own_local_date_decides_the_week_not_utc(self):
        db = database()
        # 23:30 Sunday local is already Monday in UTC; it must stay in the earlier week.
        add(db, "2026-11-22", miles=4, minutes=40, started_at_utc="2026-11-23T05:30:00+00:00")
        weeks = context(db)["weekly_mileage"]
        self.assertEqual(weeks[0]["miles"], 0.0)
        self.assertEqual(weeks[1]["miles"], 4.0)

    def test_longest_run_each_week_and_empty_weeks_are_omitted(self):
        db = database()
        add(db, "2026-11-24", miles=4, minutes=36)
        add(db, "2026-11-23", miles=9, minutes=81)
        add(db, "2026-11-10", miles=12, minutes=108)
        longs = context(db)["recent_long_runs"]
        self.assertEqual([(x["week_start"], x["distance_miles"]) for x in longs], [("2026-11-23", 9.0), ("2026-11-09", 12.0)])


class MissingVersusZeroTests(unittest.TestCase):
    def test_no_runs_means_unknown_not_zero_for_pace_and_longest(self):
        db = database()
        add(db, "2026-11-24", kind="training", sub="strength_training", minutes=40)
        w = context(db)["training_load"]["windows"]["last_7_days"]["running"]
        self.assertEqual((w["runs"], w["miles"]), (0, 0.0))                  # zero is a real answer here
        self.assertIsNone(w["longest_run_miles"])
        self.assertIsNone(w["avg_pace_min_per_mile"])
        self.assertIsNone(w["heart_rate_zone_minutes"])
        self.assertIsNone(context(db)["training_load"]["last_7_days_miles_vs_28_day_weekly_average"])

    def test_quality_sessions_are_reported_unavailable(self):
        out = context(database())
        self.assertFalse(out["quality_sessions"]["available"])
        self.assertTrue(any("Quality sessions" in m for m in out["missing"]))
        self.assertTrue(any("readiness" in m for m in out["missing"]))

    def test_undated_activities_are_called_out(self):
        db = database()
        add(db, None, miles=3, minutes=30)
        self.assertTrue(any("no local date" in m for m in context(db)["missing"]))

    def test_empty_database_does_not_crash(self):
        out = context(database())
        self.assertEqual(out["recent_activities"], [])
        self.assertIsNone(out["freshness"]["latest_activity"])


class RecentActivitiesTests(unittest.TestCase):
    def test_newest_first_and_limit(self):
        db = database()
        for day in range(15, 26):
            add(db, f"2026-11-{day}", miles=3, minutes=30)
        recent = context(db, recent_limit=3)["recent_activities"]
        self.assertEqual([a["local_date"] for a in recent], ["2026-11-25", "2026-11-24", "2026-11-23"])
        self.assertEqual(len(context(db, recent_limit=500)["recent_activities"]), 11)   # capped, not an error

    def test_flags_warn_about_unreliable_numbers(self):
        db = database()
        add(db, "2026-11-24", sub="treadmill", miles=6, minutes=54, garmin_adjusted=1, lap_distance_adjusted=1)
        flags = context(db)["recent_activities"][0]["flags"]
        self.assertEqual(sorted(flags), ["distance_or_duration_from_garmin_not_the_fit_file", "lap_distances_unreliable", "treadmill"])

    def test_pace_is_only_given_for_runs_with_real_distance(self):
        db = database()
        add(db, "2026-11-24", miles=0.01, minutes=1)
        add(db, "2026-11-23", kind="cycling", miles=10, minutes=30)
        by_date = {a["local_date"]: a for a in context(db)["recent_activities"]}
        self.assertIsNone(by_date["2026-11-24"]["pace"])
        self.assertIsNone(by_date["2026-11-23"]["pace"])      # pace is a running measure here


class FreshnessTests(unittest.TestCase):
    def test_recent_success_is_not_stale(self):
        f = context(database(), fresh_status(hours=1))["freshness"]
        self.assertFalse(f["stale"])
        self.assertEqual(f["notes"], [])

    def test_old_success_is_stale_with_a_note(self):
        f = context(database(), fresh_status(hours=5))["freshness"]
        self.assertTrue(f["stale"])
        self.assertIn("5.0 hours ago", f["notes"][0])

    def test_missing_status_file_is_stale_and_says_so(self):
        f = context(database(), None)["freshness"]
        self.assertTrue(f["stale"])
        self.assertIsNone(f["hours_since_last_successful_sync"])
        self.assertIn("freshness is unknown", f["notes"][0])

    def test_failed_last_attempt_is_reported_even_if_data_is_recent(self):
        status = dict(fresh_status(hours=1), ok=False, message="Garmin rejected the API key")
        f = context(database(), status)["freshness"]
        self.assertFalse(f["stale"])
        self.assertTrue(any("most recent sync attempt failed" in n for n in f["notes"]))

    def test_latest_activity_age(self):
        db = database()
        add(db, "2026-11-25", miles=3, minutes=30, started_at_utc="2026-11-25T12:00:00+00:00")
        self.assertEqual(context(db, fresh_status())["freshness"]["latest_activity"]["hours_ago"], 6.0)


def wellness(connection, day, **fields):
    row = {"athlete_id": 1, "calendar_date": day}
    row.update(fields)
    connection.execute(f"INSERT INTO wellness_daily({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def fill_wellness(connection, days=28, end=TODAY, **defaults):
    """One row per day, oldest first, ending on `end`. Per-day overrides: pass callables via `by_day`."""
    for offset in range(days - 1, -1, -1):
        day = (end - timedelta(days=offset)).isoformat()
        wellness(connection, day, **defaults)


class RecoveryTests(unittest.TestCase):
    NORMAL = {"sleep_seconds": 7.5 * 3600, "sleep_score": 80, "hrv_last_night_avg": 80, "hrv_balanced_low": 63,
              "hrv_balanced_upper": 110, "hrv_status": "BALANCED", "resting_hr_bpm": 42, "body_battery_at_wake": 85, "avg_stress": 25}

    def recovery(self, connection):
        return context(connection, fresh_status())["recovery"]

    def test_latest_values_and_seven_versus_twenty_eight_day_averages(self):
        db = database()
        # 21 older days of 7 h sleep / HRV 70 / resting HR 44, then a better last week
        for offset in range(27, 6, -1):
            wellness(db, (TODAY - timedelta(days=offset)).isoformat(), **dict(self.NORMAL, sleep_seconds=7 * 3600, hrv_last_night_avg=70, resting_hr_bpm=44))
        for offset in range(6, -1, -1):
            wellness(db, (TODAY - timedelta(days=offset)).isoformat(), **dict(self.NORMAL, sleep_seconds=8 * 3600, hrv_last_night_avg=90, resting_hr_bpm=38))
        r = self.recovery(db)
        self.assertEqual(r["data_through"], TODAY.isoformat())
        self.assertEqual((r["sleep"]["last_night_hours"], r["sleep"]["avg_hours_7d"], r["sleep"]["avg_hours_28d"]), (8.0, 8.0, 7.25))
        self.assertEqual((r["hrv"]["last_night_ms"], r["hrv"]["avg_7d_ms"], r["hrv"]["avg_28d_ms"]), (90, 90.0, 75.0))
        self.assertEqual((r["resting_hr_bpm"]["latest"], r["resting_hr_bpm"]["avg_7d"], r["resting_hr_bpm"]["avg_28d"]), (38, 38.0, 42.5))
        self.assertEqual(r["hrv"]["garmin_balanced_range_ms"], [63, 110])
        self.assertEqual(r["hrv"]["garmin_status"], "BALANCED")

    def test_a_normal_stretch_raises_no_flags_and_says_so_carefully(self):
        db = database()
        fill_wellness(db, **self.NORMAL)
        r = self.recovery(db)
        self.assertEqual(r["flags"], [])
        self.assertTrue(any("does not guarantee" in n for n in r["notes"]))

    def test_each_flag_rule_fires_on_its_own_threshold(self):
        db = database()
        fill_wellness(db, days=27, end=TODAY - timedelta(days=1), **self.NORMAL)
        # today: HRV under Garmin's range, resting HR +4, 5.5 h of sleep, body battery 30
        wellness(db, TODAY.isoformat(), **dict(self.NORMAL, hrv_last_night_avg=55, resting_hr_bpm=46, sleep_seconds=5.5 * 3600, body_battery_at_wake=30))
        names = {f["flag"] for f in self.recovery(db)["flags"]}
        self.assertEqual(names, {"hrv_below_garmin_range", "resting_hr_elevated", "short_sleep_last_night", "low_body_battery_at_wake"})

    def test_flags_stay_quiet_just_inside_the_thresholds(self):
        db = database()
        fill_wellness(db, days=27, end=TODAY - timedelta(days=1), **self.NORMAL)
        # resting HR 2 above average (rule is 3), sleep exactly 6 h (rule is under 6), HRV at the range floor
        wellness(db, TODAY.isoformat(), **dict(self.NORMAL, resting_hr_bpm=44, sleep_seconds=6 * 3600, hrv_last_night_avg=63, body_battery_at_wake=70))
        self.assertEqual(self.recovery(db)["flags"], [])

    def test_three_short_nights_and_a_falling_hrv_trend(self):
        db = database()
        for offset in range(27, 6, -1):
            wellness(db, (TODAY - timedelta(days=offset)).isoformat(), **dict(self.NORMAL, hrv_last_night_avg=90))
        for offset in range(6, -1, -1):
            short = offset in (1, 3, 5)
            wellness(db, (TODAY - timedelta(days=offset)).isoformat(), **dict(self.NORMAL, hrv_last_night_avg=60, sleep_seconds=(6.2 if short else 7.5) * 3600))
        r = self.recovery(db)
        names = {f["flag"] for f in r["flags"]}
        self.assertIn("several_short_nights", names)
        self.assertIn("hrv_trending_down", names)       # 7-day average 60 vs 28-day 82.5
        self.assertEqual(r["sleep"]["nights_under_6_5h_of_last_7"], 3)

    def test_missing_values_are_null_with_a_note_never_zero(self):
        db = database()
        fill_wellness(db, days=27, end=TODAY - timedelta(days=1), **self.NORMAL)
        wellness(db, TODAY.isoformat(), sleep_seconds=None, hrv_last_night_avg=None, resting_hr_bpm=41, body_battery_at_wake=None)
        r = self.recovery(db)
        self.assertIsNone(r["sleep"]["last_night_hours"])
        self.assertIsNone(r["hrv"]["last_night_ms"])
        self.assertEqual(r["resting_hr_bpm"]["latest"], 41)
        self.assertEqual(r["days_with_data"]["last_28_days"]["sleep"], 27)       # the missing night is not counted as zero
        self.assertEqual(r["days_with_data"]["last_7_days"]["hrv"], 6)
        self.assertAlmostEqual(r["sleep"]["avg_hours_28d"], 7.5)                  # averaged over nights that exist
        joined = " ".join(r["notes"])
        self.assertIn("Last night's sleep is missing", joined)
        self.assertIn("not zero", joined)
        self.assertNotIn("hrv_below_garmin_range", {f["flag"] for f in r["flags"]})   # no value, no flag

    def test_today_not_yet_synced_reports_the_latest_day_it_has(self):
        db = database()
        fill_wellness(db, days=28, end=TODAY - timedelta(days=1), **self.NORMAL)
        r = self.recovery(db)
        self.assertEqual(r["data_through"], (TODAY - timedelta(days=1)).isoformat())
        self.assertTrue(any("No recovery data for today yet" in n for n in r["notes"]))

    def test_stress_ignores_the_unfinished_day(self):
        db = database()
        fill_wellness(db, days=27, end=TODAY - timedelta(days=1), **dict(self.NORMAL, avg_stress=20))
        wellness(db, TODAY.isoformat(), **dict(self.NORMAL, avg_stress=99))        # today's average is still forming
        stress = self.recovery(db)["stress_daily_avg_full_days"]
        self.assertEqual((stress["latest"], stress["latest_date"], stress["avg_7d"], stress["avg_28d"]), (20, (TODAY - timedelta(days=1)).isoformat(), 20.0, 20.0))

    def test_no_wellness_data_says_so(self):
        r = self.recovery(database())
        self.assertFalse(r["available"])
        self.assertIn("No wellness data", r["reason"])

    def test_stays_compact_even_with_every_flag_firing(self):
        db = database()
        fill_wellness(db, days=27, end=TODAY - timedelta(days=1), **self.NORMAL)
        wellness(db, TODAY.isoformat(), **dict(self.NORMAL, hrv_last_night_avg=40, resting_hr_bpm=50, sleep_seconds=5 * 3600, body_battery_at_wake=20))
        import json
        size = len(json.dumps(self.recovery(db), separators=(",", ":")))
        self.assertLess(size, 2000, f"recovery block is {size} bytes, about {size // 4} tokens")

    def test_recovery_is_part_of_the_full_context_and_training_sections_are_unchanged(self):
        db = database()
        fill_wellness(db, **self.NORMAL)
        add(db, "2026-11-25", miles=5, minutes=45)
        out = context(db, fresh_status())
        for key in ("recovery", "training_load", "weekly_mileage", "recent_long_runs", "recent_activities", "freshness", "missing"):
            self.assertIn(key, out)
        self.assertEqual(out["training_load"]["windows"]["last_7_days"]["running"]["miles"], 5.0)
        self.assertFalse(any("Sleep, resting heart rate" in m for m in out["missing"]))     # no longer "missing"


class ReadOnlyTests(unittest.TestCase):
    def test_the_database_connection_cannot_write(self):
        import os, tempfile
        path = os.path.join(tempfile.mkdtemp(), "x.db")
        connection = sqlite3.connect(path); db_upgrade.apply_schema(connection, str(_path.ROOT / "schema.sql")); connection.close()
        read_only = tc.open_read_only(path)
        with self.assertRaises(sqlite3.OperationalError):
            read_only.execute("INSERT INTO athletes(display_name) VALUES ('x')")
        read_only.close()


if __name__ == "__main__":
    unittest.main()
