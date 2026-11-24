"""Heart-rate settings Garmin recorded in recent run files: zones, max HR, resting HR, threshold HR.

Read-only. The numbers come from the time-in-zone message inside each archived FIT file, so they are
Garmin's settings on that run's date. They change over time and are not necessarily current."""

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import fit_summary

SESSION_REFERENCE = 18          # the time-in-zone message that describes the whole session
LOOK_BACK_DAYS = (30, 90, 180, 365)
MAX_FILES_TRIED = 4
ZONE_CALC = {0: "custom", 1: "percent of max heart rate", 2: "percent of heart-rate reserve"}


@lru_cache(maxsize=32)
def read_settings(file_path):
    """Settings from one FIT file, or None when the file or the message is not there."""
    path = Path(file_path)
    if not path.exists():
        return None
    try:
        messages = fit_summary.parse_fit_all(str(path)).time_in_zone
    except Exception:
        return None
    for message in messages:
        if message.get(0) == SESSION_REFERENCE and isinstance(message.get(6), list):
            clean = lambda value: None if value in (None, 255) else value
            return {
                "max_hr": clean(message.get(11)),
                "resting_hr": clean(message.get(12)),
                "threshold_hr": clean(message.get(13)),
                "zone_boundaries_bpm": message[6],
                "zone_basis": ZONE_CALC.get(message.get(10), "unknown"),
            }
    return None


def run_files(connection, on_or_before):
    return connection.execute(
        """
        SELECT a.garmin_activity_id, a.local_date, sf.file_path
        FROM activities a JOIN source_files sf ON sf.id = a.source_file_id
        WHERE a.activity_type IN ('running', 'treadmill_running') AND a.local_date <= ?
        ORDER BY a.local_date DESC, a.started_at_utc DESC LIMIT ?
        """, (on_or_before.isoformat(), MAX_FILES_TRIED)).fetchall()


def first_readable(connection, on_or_before):
    for garmin_id, local_date, file_path in run_files(connection, on_or_before):
        settings = read_settings(file_path)
        if settings:
            return garmin_id, local_date, settings
    return None


def heart_rate_settings(connection, local_today):
    """The block for get_training_context, or None when no run file has settings."""
    latest = first_readable(connection, local_today)
    if not latest:
        return None
    garmin_id, local_date, settings = latest
    history = []
    for days in LOOK_BACK_DAYS:
        earlier = first_readable(connection, local_today - timedelta(days=days))
        if earlier and (earlier[2]["max_hr"], earlier[2]["threshold_hr"], earlier[2]["resting_hr"]) != \
                (settings["max_hr"], settings["threshold_hr"], settings["resting_hr"]):
            history.append({"local_date": earlier[1], "max_hr": earlier[2]["max_hr"],
                            "threshold_hr": earlier[2]["threshold_hr"], "resting_hr": earlier[2]["resting_hr"]})
    bounds = settings["zone_boundaries_bpm"]
    return {
        "from": {"garmin_activity_id": garmin_id, "local_date": local_date},
        "source": "Garmin's heart-rate settings as recorded in that run's FIT file",
        **settings,
        "zones_explained": "zone n runs from boundary n to boundary n+1" if len(bounds) == 6 else None,
        "earlier_values": history,
        "caution": "Garmin's settings on that run's date, not necessarily current; max and threshold HR have drifted (earlier_values). "
                   "Resting HR here looks like a fixed setting. Not recorded: whether threshold was measured or entered.",
    }
