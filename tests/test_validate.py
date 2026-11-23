import unittest
from datetime import date

from tests import _path  # noqa: F401
import validate_garmin as v

ITEM = {"startTimeGMT": "2026-11-12 10:12:56", "startTimeLocal": "2026-11-12 05:12:56",
        "distance": 10000.0, "duration": 3600.0, "averageHR": 140.0, "maxHR": 170.0}
ROW = {"started_at_utc": "2026-11-12T10:12:56+00:00", "local_date": "2026-11-12",
       "start_time_local": "2026-11-12T05:12:56", "utc_offset_minutes": -300,
       "distance_m": 10020.0, "duration_seconds": 3600.4, "avg_heart_rate_bpm": 140.0, "max_heart_rate_bpm": 170.0}


class CompareTests(unittest.TestCase):
    def test_matching_row_has_no_problems(self):
        self.assertEqual(v.compare_activity(ROW, ITEM), [])

    def test_distance_tolerance_is_half_a_percent(self):
        self.assertEqual(v.compare_activity(dict(ROW, distance_m=10049.0), ITEM), [])
        self.assertEqual(v.compare_activity(dict(ROW, distance_m=10060.0), ITEM), ["distance"])

    def test_duration_and_heart_rate_tolerances(self):
        self.assertEqual(v.compare_activity(dict(ROW, duration_seconds=3602.0), ITEM), ["duration"])
        self.assertEqual(v.compare_activity(dict(ROW, avg_heart_rate_bpm=141.5), ITEM), ["avg_hr"])
        self.assertEqual(v.compare_activity(dict(ROW, avg_heart_rate_bpm=140.9), ITEM), [])

    def test_wrong_local_date_and_offset_are_caught(self):
        # the old fixed-Chicago behaviour: right instant, wrong local clock
        wrong = dict(ROW, local_date="2026-11-11", start_time_local="2026-11-11T23:12:56", utc_offset_minutes=-360)
        self.assertEqual(sorted(v.compare_activity(wrong, ITEM)), ["local_date", "start_time_local", "utc_offset"])

    def test_missing_heart_rate_is_not_a_failure(self):
        self.assertEqual(v.compare_activity(dict(ROW, avg_heart_rate_bpm=None), ITEM), [])


class WeekTests(unittest.TestCase):
    def test_monday_start(self):
        self.assertEqual(v.monday_of(date(2026, 11, 22)), date(2026, 11, 16))  # Sunday -> its Monday
        self.assertEqual(v.monday_of(date(2026, 11, 16)), date(2026, 11, 16))

    def test_last_eight_complete_weeks_exclude_the_current_week(self):
        today = date(2026, 11, 23)  # a Monday: the week that just ended is 16-22 Nov
        totals = v.weekly_running_miles([], 8, today)
        self.assertEqual(max(totals), date(2026, 11, 16))
        self.assertEqual(len(totals), 8)
        self.assertNotIn(date(2026, 11, 23), totals)

    def test_a_sunday_night_run_belongs_to_that_week_by_local_date(self):
        today = date(2026, 11, 25)
        entries = [("2026-11-22", 1609.344), ("2026-11-23", 3218.688)]  # Sunday, then Monday
        totals = v.weekly_running_miles(entries, 2, today)
        self.assertAlmostEqual(totals[date(2026, 11, 16)], 1.0)
        self.assertNotIn(date(2026, 11, 23), totals)  # the current week is not graded


class SpotCheckTests(unittest.TestCase):
    def rows(self):
        base = {"duration_seconds": 100, "distance_m": 1, "utc_offset_minutes": -300, "lap_pace_spread": None}
        return [
            dict(base, id=1, garmin_activity_id=1, activity_type="running", sub_sport="generic", distance_m=20000),
            dict(base, id=2, garmin_activity_id=2, activity_type="running", sub_sport="generic", distance_m=5000, lap_pace_spread=0.9),
            dict(base, id=3, garmin_activity_id=3, activity_type="running", sub_sport="treadmill", distance_m=8000),
            dict(base, id=4, garmin_activity_id=4, activity_type="training", sub_sport="strength_training", duration_seconds=3000),
            dict(base, id=5, garmin_activity_id=5, activity_type="running", sub_sport="generic", distance_m=7000, utc_offset_minutes=480),
        ]

    def test_picks_one_of_each_kind(self):
        picks = v.pick_spot_checks(self.rows())
        self.assertEqual(picks["long run"]["id"], 1)
        self.assertEqual(picks["interval-like run (derived from lap pace variation)"]["id"], 2)
        self.assertEqual(picks["treadmill run"]["id"], 3)
        self.assertEqual(picks["strength session"]["id"], 4)
        self.assertEqual(picks["recorded while traveling"]["id"], 5)

    def test_omits_a_kind_when_none_exists(self):
        picks = v.pick_spot_checks([r for r in self.rows() if r["id"] != 5])
        self.assertNotIn("recorded while traveling", picks)


if __name__ == "__main__":
    unittest.main()
