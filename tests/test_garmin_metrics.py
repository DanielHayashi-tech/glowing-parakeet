import json
import sqlite3
import unittest

from tests import _path  # noqa: F401
import db_upgrade
import garmin_metrics as metrics


def database(**activity):
    connection = sqlite3.connect(":memory:")
    db_upgrade.apply_schema(connection, str(_path.ROOT / "schema.sql"))
    connection.execute("INSERT INTO athletes(id, display_name) VALUES (1, 'a')")
    row = {"athlete_id": 1, "activity_type": "running", "sport": "running", "garmin_activity_id": 100,
           "started_at_utc": "2026-11-12T10:12:56+00:00", "distance_m": 10000.0, "duration_seconds": 3600.0,
           "avg_heart_rate_bpm": 140.4, "avg_cadence_spm": 150.0}
    row.update(activity)
    connection.execute(f"INSERT INTO activities({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    return connection


ITEM = {"activityId": 100, "activityName": "Morning Run", "startTimeGMT": "2026-11-12 10:12:56",
        "startTimeLocal": "2026-11-12 05:12:56", "distance": 10000.0, "duration": 3600.0, "averageHR": 141.0,
        "maxHR": 170.0, "aerobicTrainingEffect": 3.1, "activityTrainingLoad": 80.5, "hrTimeInZone_2": 1200.0,
        "activityType": {"typeKey": "running"}, "averageRunningCadenceInStepsPerMinute": 160.5}


def one(connection, column):
    return connection.execute(f"SELECT {column} FROM activities").fetchone()[0]


class ApplyItemsTests(unittest.TestCase):
    def test_stores_garmin_metrics_local_time_and_raw_json(self):
        connection = database()
        counts = metrics.apply_items(connection, [ITEM])
        self.assertEqual(counts["activities_updated"], 1)
        self.assertEqual(one(connection, "local_date"), "2026-11-12")
        self.assertEqual(one(connection, "utc_offset_minutes"), -300)
        self.assertEqual(one(connection, "aerobic_training_effect"), 3.1)
        self.assertEqual(one(connection, "training_load"), 80.5)
        self.assertEqual(one(connection, "hr_zone2_seconds"), 1200.0)
        self.assertEqual(one(connection, "avg_heart_rate_bpm"), 141.0)       # Garmin's value, not the sample average
        self.assertEqual(one(connection, "avg_cadence_spm"), 160.5)
        raw = connection.execute("SELECT payload, fit_status FROM garmin_activity_raw WHERE garmin_activity_id = 100").fetchone()
        self.assertEqual(json.loads(raw[0])["activityName"], "Morning Run")
        self.assertEqual(raw[1], "imported")

    def test_matching_values_are_not_flagged_as_adjusted(self):
        connection = database(distance_m=10020.0, duration_seconds=3600.5)   # within 0.5% and 1 s
        metrics.apply_items(connection, [ITEM])
        self.assertEqual(one(connection, "garmin_adjusted"), 0)

    def test_garmin_value_wins_and_the_fit_original_is_kept_when_they_differ(self):
        connection = database(distance_m=0.0, duration_seconds=3000.0)       # indoor ride: FIT has no distance
        item = dict(ITEM, distance=20004.0, duration=3600.0)
        metrics.apply_items(connection, [item])
        self.assertEqual(one(connection, "distance_m"), 20004.0)
        self.assertEqual(one(connection, "duration_seconds"), 3600.0)
        self.assertEqual(one(connection, "fit_distance_m"), 0.0)
        self.assertEqual(one(connection, "fit_duration_seconds"), 3000.0)
        self.assertEqual(one(connection, "garmin_adjusted"), 1)

    def test_repeating_is_safe_and_never_overwrites_the_fit_original(self):
        connection = database(distance_m=1387.0)
        item = dict(ITEM, distance=1690.0)
        metrics.apply_items(connection, [item])
        metrics.apply_items(connection, [item])
        self.assertEqual(one(connection, "fit_distance_m"), 1387.0)
        self.assertEqual(one(connection, "distance_m"), 1690.0)

    def test_start_is_corrected_to_garmins(self):
        connection = database(started_at_utc="2026-11-12T11:00:00+00:00")   # the old 47-minute parser error
        counts = metrics.apply_items(connection, [ITEM])
        self.assertEqual(counts["start_corrected"], 1)
        self.assertEqual(one(connection, "started_at_utc"), "2026-11-12T10:12:56+00:00")

    def test_missing_garmin_values_never_overwrite_with_null(self):
        connection = database()
        metrics.apply_items(connection, [{"activityId": 100, "startTimeGMT": ITEM["startTimeGMT"], "startTimeLocal": ITEM["startTimeLocal"]}])
        self.assertEqual(one(connection, "distance_m"), 10000.0)
        self.assertEqual(one(connection, "avg_heart_rate_bpm"), 140.4)

    def test_unimported_activities_still_keep_raw_json_and_stay_pending(self):
        connection = database()
        counts = metrics.apply_items(connection, [dict(ITEM, activityId=999)])
        self.assertEqual(counts["not_imported"], 1)
        status = connection.execute("SELECT fit_status FROM garmin_activity_raw WHERE garmin_activity_id = 999").fetchone()[0]
        self.assertEqual(status, "pending")
        metrics.record_unavailable(connection, [999], [])
        self.assertEqual(connection.execute("SELECT fit_status FROM garmin_activity_raw WHERE garmin_activity_id = 999").fetchone()[0], "no_original")


if __name__ == "__main__":
    unittest.main()
