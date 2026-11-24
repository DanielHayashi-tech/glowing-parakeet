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
