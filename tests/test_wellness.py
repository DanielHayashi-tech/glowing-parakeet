import sqlite3
import unittest
from datetime import date

from tests import _path  # noqa: F401
import db_upgrade
import sync_garmin_wellness as wellness

TODAY = date(2026, 11, 23)


def database():
    connection = sqlite3.connect(":memory:")
    db_upgrade.apply_schema(connection, str(_path.ROOT / "schema.sql"))
    connection.execute("INSERT INTO athletes(id, display_name) VALUES (1, 'a')")
    return connection


class DaysToFetchTests(unittest.TestCase):
    def test_empty_database_fetches_the_whole_window(self):
        days = wellness.days_to_fetch(database(), 1, TODAY, window_days=10)
        self.assertEqual(len(days), 11)
        self.assertEqual(days[0], date(2026, 11, 13))
        self.assertEqual(days[-1], TODAY)

    def test_settled_days_are_skipped_but_the_recent_days_are_always_refreshed(self):
        connection = database()
        for offset in range(0, 11):  # every day in the window is settled
            day = date(2026, 11, 13 + offset).isoformat()
            wellness.log_day(connection, 1, day, "ok")
        days = wellness.days_to_fetch(connection, 1, TODAY, window_days=10)
        self.assertEqual(days, [date(2026, 11, 21), date(2026, 11, 22), date(2026, 11, 23)])

    def test_empty_days_count_as_settled_and_errors_are_retried(self):
        connection = database()
        wellness.log_day(connection, 1, "2026-11-13", "empty")
        wellness.log_day(connection, 1, "2026-11-14", "error", "HTTP 500")
        days = wellness.days_to_fetch(connection, 1, TODAY, window_days=10)
        self.assertNotIn(date(2026, 11, 13), days)
        self.assertIn(date(2026, 11, 14), days)

    def test_days_stored_before_the_log_existed_count_as_settled(self):
        connection = database()
        connection.execute("INSERT INTO wellness_daily(athlete_id, calendar_date) VALUES (1, '2026-11-13')")
        self.assertNotIn(date(2026, 11, 13), wellness.days_to_fetch(connection, 1, TODAY, window_days=10))

    def test_explicit_start_extends_the_range_back(self):
        days = wellness.days_to_fetch(database(), 1, TODAY, start=date(2025, 3, 1))
        self.assertEqual(days[0], date(2025, 3, 1))
        self.assertEqual(len(days), (TODAY - date(2025, 3, 1)).days + 1)


class FakeClient:
    """Returns canned JSON per endpoint; None means Garmin has nothing."""

    def __init__(self, data_days=(), fail_days=()):
        self.data_days, self.fail_days = set(data_days), set(fail_days)

    def _request(self, path, accept):
        day = path[-10:]
        if day in self.fail_days:
            raise wellness.garmin.GarminError("boom")
        if day not in self.data_days:
            return None
        if "usersummary" in path:
            return b'{"totalSteps": 1000, "restingHeartRate": 44}'
        return b'{"x": 1}'


class RunTests(unittest.TestCase):
    def run_with(self, client, db_path):
        wellness.REQUEST_DELAY_SECONDS = 0
        return wellness.run(db_path, "a", "America/Chicago", lambda m: None, client=client, today=TODAY,
                            start=date(2026, 11, 20))

    def test_records_ok_empty_and_error_days_distinctly(self):
        import os, tempfile
        path = os.path.join(tempfile.mkdtemp(), "w.db")
        client = FakeClient(data_days={"2026-11-21"}, fail_days={"2026-11-22"})
        previous = os.getcwd()
        os.chdir(_path.ROOT)
        try:
            summary = self.run_with(client, path)
        finally:
            os.chdir(previous)
        connection = sqlite3.connect(path)
        statuses = dict(connection.execute("SELECT calendar_date, status FROM wellness_fetch_log"))
        self.assertEqual(statuses["2026-11-21"], "ok")
        self.assertEqual(statuses["2026-11-22"], "error")
        self.assertEqual(statuses["2026-11-20"], "empty")
        self.assertEqual((summary["days_stored"], summary["days_failed"]), (1, 1))
        self.assertEqual(connection.execute("SELECT resting_hr_bpm FROM wellness_daily").fetchone()[0], 44)


if __name__ == "__main__":
    unittest.main()
