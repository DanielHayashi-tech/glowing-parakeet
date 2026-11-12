#!/usr/bin/env python
"""Fetch new Garmin activities, then import everything waiting in the inbox.

One entry point for the Sync button and the nightly job, so both do exactly the
same thing. Files dropped into raw/garmin/inbox by hand are imported too, which
keeps a manual fallback if the Garmin key ever stops working.

Usage:
    python run_sync.py
    python run_sync.py --json                 # machine-readable, used by the app
    python run_sync.py --trigger nightly --notify
"""

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Relative paths below (and .env) resolve against the repo, wherever we are launched from.
os.chdir(Path(__file__).resolve().parent)

import sync_garmin_api as garmin  # noqa: E402

ATHLETE_NAME = "D Hayashi"
TIMEZONE = "America/Chicago"
INBOX = Path("raw/garmin/inbox")
ARCHIVE = Path("raw/garmin/archive")
FAILED = Path("raw/garmin/failed")
STATUS_PATH = Path("temp/last_sync.json")
LOCK_PATH = Path("temp/sync.lock")
IMPORT_TIMEOUT_SECONDS = 15 * 60
KEY_WARN_DAYS = 14
KEY_NOTIFY_DAYS = 7
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
    if result["sync_error"]:
        parts.append(f"Garmin sync failed: {result['sync_error']}")
    if result["import_error"]:
        parts.append(f"Import failed: {result['import_error']}")
    days = result["key_days_left"]
    if days is not None and days <= KEY_WARN_DAYS:
        if days < 0:
            parts.append("The Garmin key has expired. Generate a new one in Garmin Connect.")
        else:
            parts.append(f"The Garmin key expires in {plural(days, 'day')}. Generate a new one in Garmin Connect.")
    return " ".join(parts)


def run_import(log):
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
            command, capture_output=True, text=True, timeout=IMPORT_TIMEOUT_SECONDS
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
    }

    garmin.load_dotenv()
    result["key_days_left"] = key_days_left()
    sync_args = argparse.Namespace(
        inbox=str(INBOX),
        db="data_hub.db",
        limit=args.limit,
        since=args.since,
        full=args.full,
        dry_run=False,
    )
    try:
        result["sync"] = garmin.run(sync_args, log)
    except garmin.GarminError as error:
        result["sync_error"] = str(error)

    had_files = any(INBOX.rglob("*.fit")) if INBOX.exists() else False
    if had_files:
        counts, error = run_import(log)
        if counts:
            result.update(counts)
        result["import_error"] = error

    result["ok"] = not result["sync_error"] and not result["import_error"]
    result["message"] = build_message(result, had_files)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    return result


def write_status(result):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    keys = ("trigger", "ok", "message", "started_at", "finished_at", "imported", "skipped", "failed", "key_days_left")
    STATUS_PATH.write_text(json.dumps({key: result[key] for key in keys}, indent=2), encoding="utf-8")


def notify(message, ok, days_left=None):
    """macOS notification after every run, so you know it ran (and a failure, like an expired key, is never silent)."""
    escaped = message.replace("\\", "\\\\").replace('"', '\\"')
    if not ok:
        title = "move2Zero sync needs attention"
    elif days_left is not None and days_left <= KEY_NOTIFY_DAYS:
        title = "move2Zero sync: Garmin key expires soon"
    else:
        title = "move2Zero sync"
    script = f'display notification "{escaped}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True, check=False)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=50, help="Max new activities to download per run.")
    parser.add_argument("--since", default=None, help="Only consider activities on/after YYYY-MM-DD.")
    parser.add_argument("--full", action="store_true", help="Keep paging past known activities (backfill).")
    parser.add_argument("--json", action="store_true", help="Print a JSON result on stdout.")
    parser.add_argument("--trigger", default="manual", help="Who started this run: manual or nightly.")
    parser.add_argument("--notify", action="store_true", help="Show a macOS notification when the run finishes (success or failure).")
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
    result = run_all(args, log)
    write_status(result)

    if args.notify:
        notify(result["message"], result["ok"], result["key_days_left"])

    if args.json:
        result["log"] = lines
        print(json.dumps(result))
    else:
        print(result["message"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
