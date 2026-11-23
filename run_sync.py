#!/usr/bin/env python
"""Fetch new Garmin activities, then import everything waiting in the inbox.

One entry point for the Sync button and the scheduled job, so both do exactly the
same thing. Files dropped into raw/garmin/inbox by hand are imported too, which
keeps a manual fallback if the Garmin key ever stops working.

Usage:
    python run_sync.py
    python run_sync.py --json                 # machine-readable, used by the app
    python run_sync.py --trigger scheduled --notify
"""

import argparse
import fcntl
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Relative paths below (and .env) resolve against the repo, wherever we are launched from.
os.chdir(Path(__file__).resolve().parent)

import sync_garmin_api as garmin  # noqa: E402
import sync_garmin_wellness as wellness  # noqa: E402
import garmin_metrics  # noqa: E402
from db_upgrade import apply_schema  # noqa: E402

ATHLETE_NAME = "D Hayashi"
TIMEZONE = "America/Chicago"
INBOX = Path("raw/garmin/inbox")
ARCHIVE = Path("raw/garmin/archive")
FAILED = Path("raw/garmin/failed")
STATUS_PATH = Path("temp/last_sync.json")
LOCK_PATH = Path("temp/sync.lock")
IMPORT_TIMEOUT_SECONDS = 15 * 60
IMPORT_SECONDS_PER_FILE = 8  # a backfill of hundreds of files needs more than the base timeout
KEY_WARN_DAYS = 14
KEY_NOTIFY_DAYS = 7
REPEAT_FAILURE_NOTIFY_HOURS = 6  # an offline Mac fails every hour; do not alert every hour
DONE_PATTERN = re.compile(r"Done\. imported=(\d+) skipped=(\d+) failed=(\d+)")


def plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def activities(count):
    return "1 activity" if count == 1 else f"{count} activities"


def key_days_left():
    """Days until the Garmin key expires, from GARMIN_KEY_EXPIRES=YYYY-MM-DD in .env.

    Garmin does not expose the key's expiry through the API, so the date is
    copied from Garmin Connect by hand. Returns None when unset or unreadable.
    """
    raw = os.environ.get("GARMIN_KEY_EXPIRES", "").strip()
    if not raw:
        return None
    try:
        return (date.fromisoformat(raw) - date.today()).days
    except ValueError:
        return None


def build_message(result, had_files):
    parts = []
    sync = result["sync"]
    if sync:
        if sync["downloaded"] == 0 and not had_files:
            parts.append(f"Already up to date (checked {activities(sync['checked'])}).")
        else:
            parts.append(f"Checked {activities(sync['checked'])}, downloaded {sync['downloaded']}.")
    if had_files and not result["import_error"]:
        text = f"Imported {result['imported']}"
        if result["skipped"]:
            text += f", {plural(result['skipped'], 'duplicate')} cleared"
        if result["failed"]:
            text += f", {result['failed']} failed"
        parts.append(text + ".")
    if result["wellness"] and result["wellness"]["days_stored"] and not result["wellness_error"]:
        parts.append(f"Wellness updated for {plural(result['wellness']['days_stored'], 'day')}.")
    if result["sync_error"]:
        parts.append(f"Garmin sync failed: {result['sync_error']}")
    if result["wellness_error"]:
        parts.append(f"Wellness sync failed: {result['wellness_error']}")
    if result["metrics_error"]:
        parts.append(f"Saving Garmin metrics failed: {result['metrics_error']}")
    if result["import_error"]:
        parts.append(f"Import failed: {result['import_error']}")
    days = result["key_days_left"]
    if days is not None and days <= KEY_WARN_DAYS:
        if days < 0:
            parts.append("The Garmin key has expired. Generate a new one in Garmin Connect.")
        else:
            parts.append(f"The Garmin key expires in {plural(days, 'day')}. Generate a new one in Garmin Connect.")
    return " ".join(parts)


def run_import(log, file_count=0):
    """Import and archive whatever is in the inbox. Returns (counts, error)."""
    command = [
        sys.executable,
        "import_garmin_fit.py",
        "--fit-root", str(INBOX),
        "--timezone", TIMEZONE,
        "--run-mode", "inbox",
        "--archive-root", str(ARCHIVE),
        "--failed-root", str(FAILED),
        "--athlete-name", ATHLETE_NAME,
        "--notes", "source=garmin_sync",
    ]
    try:
        process = subprocess.run(
            command, capture_output=True, text=True,
            timeout=IMPORT_TIMEOUT_SECONDS + IMPORT_SECONDS_PER_FILE * file_count,
        )
    except subprocess.TimeoutExpired:
        return None, "the importer timed out. Run it again to continue."

    for line in process.stdout.splitlines():
        if line.startswith(("FAILED", "Done.")):
            log(line)
    match = DONE_PATTERN.search(process.stdout)
    if process.returncode != 0 or not match:
        stderr_lines = process.stderr.strip().splitlines()
        return None, stderr_lines[-1] if stderr_lines else "the importer exited unexpectedly."
    imported, skipped, failed = (int(value) for value in match.groups())
    return {"imported": imported, "skipped": skipped, "failed": failed}, None


def run_all(args, log):
    result = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "trigger": args.trigger,
        "sync": None,
        "sync_error": None,
        "imported": 0,
        "skipped": 0,
        "failed": 0,
        "import_error": None,
        "wellness": None,
        "wellness_error": None,
        "metrics": None,
        "metrics_error": None,
    }

    garmin.load_dotenv()
    result["key_days_left"] = key_days_left()
    sync_args = argparse.Namespace(
        inbox=str(INBOX),
        db="data_hub.db",
        limit=None if args.limit == 0 else args.limit,  # 0 = no limit (full backfill)
        since=args.since,
        full=args.full,
        dry_run=False,
    )
    items, no_original_ids, invalid_ids = [], [], []
    try:
        result["sync"] = garmin.run(sync_args, log)
        # Internal detail for the metrics step below; keep the reported summary small.
        items = result["sync"].pop("items", [])
        no_original_ids = result["sync"].pop("no_original_ids", [])
        invalid_ids = result["sync"].pop("invalid_ids", [])
    except garmin.GarminError as error:
        result["sync_error"] = str(error)

    waiting = list(INBOX.rglob("*.fit")) if INBOX.exists() else []
    had_files = bool(waiting)
    if had_files:
        counts, error = run_import(log, len(waiting))
        if counts:
            result.update(counts)
        result["import_error"] = error

    # Garmin's own values (training effect, load, HR zones, local time) and the explicit
    # status of any activity with no usable FIT. Safe to repeat every run.
    if items or no_original_ids or invalid_ids:
        try:
            connection = sqlite3.connect("data_hub.db")
            try:
                apply_schema(connection)
                result["metrics"] = garmin_metrics.apply_items(connection, items)
                garmin_metrics.record_unavailable(connection, no_original_ids, invalid_ids)
            finally:
                connection.close()
        except sqlite3.Error as error:
            result["metrics_error"] = str(error)

    # Same key as the activity sync, so skip when that was just rejected.
    if not result["sync_error"] and not args.skip_wellness:
        try:
            result["wellness"] = wellness.run(
                "data_hub.db", ATHLETE_NAME, TIMEZONE, log, backfill_days=args.wellness_days,
                start=date.fromisoformat(args.wellness_from) if args.wellness_from else None,
            )
            if result["wellness"]["days_failed"]:
                failed = result["wellness"]
                result["wellness_error"] = (
                    f"{plural(failed['days_failed'], 'day')} failed: {failed['first_error']}"
                )
        except garmin.GarminError as error:
            result["wellness_error"] = str(error)

    result["ok"] = not (
        result["sync_error"] or result["import_error"] or result["wellness_error"] or result["metrics_error"]
    )
    result["message"] = build_message(result, had_files)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    return result


def merge_status(previous, result):
    """Status for temp/last_sync.json: this attempt, plus facts that must survive a failed attempt.

    last_success_at only moves when a run fully succeeds, so "stale" can be judged from it.
    """
    previous = previous or {}
    keys = ("trigger", "ok", "message", "started_at", "finished_at", "imported", "skipped", "failed", "key_days_left")
    status = {key: result.get(key) for key in keys}
    status["last_success_at"] = result["finished_at"] if result["ok"] else previous.get("last_success_at")
    status["failure_notified_at"] = previous.get("failure_notified_at")
    status["key_warned_on"] = previous.get("key_warned_on")
    return status


def read_status(path=STATUS_PATH):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def notification_for(result, previous, now):
    """(title, message) to show, or None. Hourly runs must stay quiet unless something matters:
    a failure (not repeated within 6 h), new activities, or the key running out (once a day)."""
    previous = previous or {}
    if not result["ok"]:
        last = previous.get("failure_notified_at")
        if last:
            hours = (now - datetime.fromisoformat(last)).total_seconds() / 3600
            if hours < REPEAT_FAILURE_NOTIFY_HOURS:
                return None
        return "move2Zero sync needs attention", result["message"]
    days = result.get("key_days_left")
    if days is not None and days <= KEY_NOTIFY_DAYS and previous.get("key_warned_on") != now.date().isoformat():
        return "move2Zero sync: Garmin key expires soon", result["message"]
    downloaded = (result.get("sync") or {}).get("downloaded", 0)
    if downloaded:
        return "move2Zero sync", result["message"]
    return None


def write_status(status):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")


def notify(title, message):
    """macOS notification so a failure (like an expired key) is never silent."""
    escaped = message.replace("\\", "\\\\").replace('"', '\\"')
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{escaped}" with title "{escaped_title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True, check=False)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=50, help="Max new activities to download per run (0 = no limit).")
    parser.add_argument("--since", default=None, help="Only consider activities on/after YYYY-MM-DD.")
    parser.add_argument("--full", action="store_true", help="Keep paging past known activities (backfill).")
    parser.add_argument(
        "--wellness-days", type=int, default=wellness.BACKFILL_DAYS,
        help="How far back wellness data may be backfilled on the first run.",
    )
    parser.add_argument(
        "--wellness-from", default=None,
        help="Backfill wellness from this date (YYYY-MM-DD); days already settled are skipped.",
    )
    parser.add_argument("--skip-wellness", action="store_true", help="Only sync activities.")
    parser.add_argument("--json", action="store_true", help="Print a JSON result on stdout.")
    parser.add_argument("--trigger", default="manual", help="Who started this run: manual or scheduled.")
    parser.add_argument("--notify", action="store_true", help="Notify (macOS) on failure, new activities, or an expiring key; quiet otherwise.")
    return parser.parse_args()


def main():
    args = parse_args()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        message = "Another sync is already running."
        print(json.dumps({"ok": False, "message": message, "log": []}) if args.json else message)
        return 2

    lines = []
    # With --json, stdout carries only the result; progress goes into result["log"].
    log = lines.append if args.json else print
    previous = read_status()
    result = run_all(args, log)
    status = merge_status(previous, result)

    if args.notify:
        now = datetime.now(timezone.utc)
        note = notification_for(result, previous, now)
        if note:
            notify(*note)
            if not result["ok"]:
                status["failure_notified_at"] = now.isoformat()
            elif result.get("key_days_left") is not None and result["key_days_left"] <= KEY_NOTIFY_DAYS:
                status["key_warned_on"] = now.date().isoformat()
    write_status(status)

    if args.json:
        result["log"] = lines
        print(json.dumps(result))
    else:
        print(result["message"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
