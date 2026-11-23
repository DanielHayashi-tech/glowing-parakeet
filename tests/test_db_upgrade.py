import sqlite3
import unittest

from tests import _path  # noqa: F401
import db_upgrade as upgrade
import import_garmin_fit as importer


def old_style_database():
    """A database as it was before Milestone 1: no Garmin ID or local-time columns."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE athletes (id INTEGER PRIMARY KEY, display_name TEXT);
        CREATE TABLE source_files (id INTEGER PRIMARY KEY, file_name TEXT);
        CREATE TABLE activities (
            id INTEGER PRIMARY KEY, athlete_id INTEGER, source_file_id INTEGER,
            source_activity_id TEXT, activity_type TEXT, sport TEXT,
            started_at_utc TEXT, distance_m REAL);
        CREATE TABLE laps (id INTEGER PRIMARY KEY, activity_id INTEGER, distance_m REAL);
        INSERT INTO athletes VALUES (1, 'a');
        INSERT INTO source_files VALUES (1, '111_ACTIVITY.fit'), (2, '222_ACTIVITY.fit'), (3, 'manual.fit');
        INSERT INTO activities (id, athlete_id, source_file_id, activity_type, sport, started_at_utc, distance_m)
          VALUES (1, 1, 1, 'running', 'running', '2026-01-01T10:00:00+00:00', 5000),
                 (2, 1, 2, 'running', 'running', '2026-01-02T10:00:00+00:00', 6000),
                 (3, 1, 3, 'running', 'running', '2026-01-03T10:00:00+00:00', 7000);
        """
    )
    return connection


class UpgradeTests(unittest.TestCase):
    def test_adds_columns_and_fills_garmin_ids(self):
        connection = old_style_database()
        result = upgrade.upgrade(connection)
        self.assertIn("garmin_activity_id", result["columns_added"])
        self.assertEqual(result["garmin_ids_filled"], 2)
        ids = dict(connection.execute("select id, garmin_activity_id from activities"))
        self.assertEqual(ids, {1: 111, 2: 222, 3: None})  # manual.fit has no ID in its name

    def test_is_idempotent(self):
        connection = old_style_database()
        upgrade.upgrade(connection)
        second = upgrade.upgrade(connection)
        self.assertEqual(second, {"columns_added": [], "garmin_ids_filled": 0, "lap_checks_filled": 0})

    def test_database_rejects_a_second_row_for_the_same_garmin_activity(self):
        connection = old_style_database()
        upgrade.upgrade(connection)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO activities (athlete_id, activity_type, started_at_utc, garmin_activity_id) "
                "VALUES (1, 'running', '2026-02-01T00:00:00+00:00', 111)"
            )

    def test_files_without_an_id_are_allowed_many_times(self):
        connection = old_style_database()
        upgrade.upgrade(connection)
        for day in (10, 11):
            connection.execute(
                "INSERT INTO activities (athlete_id, activity_type, started_at_utc) VALUES (1, 'running', ?)",
                (f"2026-02-{day}T00:00:00+00:00",),
            )

    def test_fresh_schema_and_upgraded_schema_have_the_same_columns(self):
        fresh = sqlite3.connect(":memory:")
        upgrade.apply_schema(fresh, str(_path.ROOT / "schema.sql"))
        fresh_columns = {r[1] for r in fresh.execute("pragma table_info(activities)")}
        for name in upgrade.ACTIVITY_COLUMNS:
            self.assertIn(name, fresh_columns)


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.connection = old_style_database()
        upgrade.upgrade(self.connection)

    def test_matches_by_garmin_activity_id(self):
        found = importer.find_duplicate_activity(
            self.connection, {"garmin_activity_id": 111, "started_at_utc": "x", "sport": "running", "distance_m": 1}
        )
        self.assertEqual(found, 1)

    def test_falls_back_to_start_time_sport_and_distance(self):
        same = {"garmin_activity_id": None, "started_at_utc": "2026-01-03T10:00:00+00:00", "sport": "running", "distance_m": 7010}
        different_distance = dict(same, distance_m=9000)
        self.assertEqual(importer.find_duplicate_activity(self.connection, same), 3)
        self.assertIsNone(importer.find_duplicate_activity(self.connection, different_distance))

    def test_new_activity_is_not_a_duplicate(self):
        new = {"garmin_activity_id": 999, "started_at_utc": "2030-01-01T00:00:00+00:00", "sport": "running", "distance_m": 1}
        self.assertIsNone(importer.find_duplicate_activity(self.connection, new))


if __name__ == "__main__":
    unittest.main()


class LapCheckTests(unittest.TestCase):
    def test_flags_only_when_laps_disagree_with_session_by_more_than_one_percent(self):
        connection = old_style_database()
        upgrade.upgrade(connection)
        # activity 1: 5000 m session, laps total 5020 (0.4%): fine. activity 2: 6000 m, laps 5400 (10%): flagged.
        connection.executemany("INSERT INTO laps(activity_id, distance_m) VALUES (?, ?)",
                               [(1, 2500), (1, 2520), (2, 2700), (2, 2700)])
        self.assertEqual(upgrade.fill_lap_checks(connection), 2)
        rows = {r[0]: r[1:] for r in connection.execute("select id, lap_distance_sum_m, lap_distance_adjusted from activities")}
        self.assertEqual(rows[1], (5020, 0))
        self.assertEqual(rows[2], (5400, 1))
        self.assertEqual(rows[3], (None, None))  # no laps: nothing to compare
