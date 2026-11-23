import unittest
from datetime import datetime, timezone

from tests import _path  # noqa: F401
import fit_summary as fs


class CadenceTests(unittest.TestCase):
    def test_foot_sports_double_per_leg_cadence(self):
        self.assertEqual(fs.cadence_to_spm(80, "running"), 160)
        self.assertEqual(fs.cadence_to_spm(50, "walking"), 100)

    def test_cycling_and_others_are_not_doubled(self):
        self.assertEqual(fs.cadence_to_spm(90, "cycling"), 90)
        self.assertEqual(fs.cadence_to_spm(90, "training"), 90)

    def test_invalid_255_sentinel_becomes_none_not_510(self):
        # The strength sessions used to store 510 (255 doubled).
        self.assertIsNone(fs.session_cadence({18: 255}, 18, 92, "training"))
        self.assertIsNone(fs.session_cadence({}, 18, 92, "running"))

    def test_running_session_cadence_includes_fractional_part(self):
        # 78 + 53/128 per leg, doubled = Garmin's 156.83 steps/min
        value = fs.session_cadence({18: 78, 92: 53}, 18, 92, "running")
        self.assertAlmostEqual(value, 156.828125, places=4)


class LocalTimeTests(unittest.TestCase):
    def test_offset_from_activity_message(self):
        # local clock is 5 hours behind UTC
        self.assertEqual(fs.utc_offset_minutes({253: 1_000_000_000, 5: 1_000_000_000 - 5 * 3600}), -300)
        self.assertEqual(fs.utc_offset_minutes({253: 1_000_000_000, 5: 1_000_000_000 + 8 * 3600}), 480)

    def test_offset_unavailable_or_implausible_is_none(self):
        self.assertIsNone(fs.utc_offset_minutes(None))
        self.assertIsNone(fs.utc_offset_minutes({253: 1_000_000_000}))
        self.assertIsNone(fs.utc_offset_minutes({253: 1_000_000_000, 5: 1_000_000_000 + 20 * 3600}))

    def test_local_date_changes_across_midnight(self):
        start = datetime(2026, 8, 29, 4, 30, tzinfo=timezone.utc)
        self.assertEqual(fs.local_fields(start, -300), ("2026-08-28T23:30:00", "2026-08-28"))
        self.assertEqual(fs.local_fields(start, 480), ("2026-08-29T12:30:00", "2026-08-29"))

    def test_daylight_saving_uses_each_activitys_own_offset(self):
        # US spring-forward on 2026-03-08: one hour apart in UTC, different offsets locally.
        before = datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)   # 01:30 CST (-360)
        after = datetime(2026, 3, 8, 8, 30, tzinfo=timezone.utc)     # 03:30 CDT (-300)
        self.assertEqual(fs.local_fields(before, -360)[0], "2026-03-08T01:30:00")
        self.assertEqual(fs.local_fields(after, -300)[0], "2026-03-08T03:30:00")

    def test_garmin_activity_id_from_filename(self):
        self.assertEqual(fs.garmin_activity_id_from_name("raw/garmin/inbox/25053054371_ACTIVITY.fit"), 25053054371)
        self.assertIsNone(fs.garmin_activity_id_from_name("my_run.fit"))


if __name__ == "__main__":
    unittest.main()
