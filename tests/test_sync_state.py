import unittest
from datetime import datetime, timedelta, timezone

from tests import _path  # noqa: F401
import run_sync

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def result(ok=True, downloaded=0, key_days=None, finished="2026-11-23T12:00:00+00:00"):
    return {"ok": ok, "message": "msg", "finished_at": finished, "key_days_left": key_days,
            "sync": {"downloaded": downloaded}, "trigger": "scheduled", "started_at": finished}


class StatusTests(unittest.TestCase):
    def test_last_success_moves_only_on_success(self):
        first = run_sync.merge_status(None, result(ok=True, finished="2026-11-23T10:00:00+00:00"))
        self.assertEqual(first["last_success_at"], "2026-11-23T10:00:00+00:00")
        failed = run_sync.merge_status(first, result(ok=False, finished="2026-11-23T11:00:00+00:00"))
        self.assertEqual(failed["last_success_at"], "2026-11-23T10:00:00+00:00")  # unchanged by the failure
        self.assertFalse(failed["ok"])
        again = run_sync.merge_status(failed, result(ok=True, finished="2026-11-23T12:00:00+00:00"))
        self.assertEqual(again["last_success_at"], "2026-11-23T12:00:00+00:00")

    def test_a_failure_before_any_success_has_no_last_success(self):
        self.assertIsNone(run_sync.merge_status(None, result(ok=False))["last_success_at"])


class NotificationTests(unittest.TestCase):
    def test_quiet_when_nothing_new(self):
        self.assertIsNone(run_sync.notification_for(result(), None, NOW))

    def test_notifies_when_new_activities_arrive(self):
        self.assertIsNotNone(run_sync.notification_for(result(downloaded=2), None, NOW))

    def test_failure_notifies_once_then_stays_quiet_for_six_hours(self):
        self.assertIsNotNone(run_sync.notification_for(result(ok=False), None, NOW))
        recent = {"failure_notified_at": (NOW - timedelta(hours=1)).isoformat()}
        self.assertIsNone(run_sync.notification_for(result(ok=False), recent, NOW))
        old = {"failure_notified_at": (NOW - timedelta(hours=7)).isoformat()}
        self.assertIsNotNone(run_sync.notification_for(result(ok=False), old, NOW))

    def test_expiring_key_warns_once_per_day(self):
        self.assertIsNotNone(run_sync.notification_for(result(key_days=3), None, NOW))
        warned_today = {"key_warned_on": NOW.date().isoformat()}
        self.assertIsNone(run_sync.notification_for(result(key_days=3), warned_today, NOW))
        self.assertIsNone(run_sync.notification_for(result(key_days=30), None, NOW))


if __name__ == "__main__":
    unittest.main()
