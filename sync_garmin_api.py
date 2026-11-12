#!/usr/bin/env python
"""Pull new activity FIT files from the Garmin Personal API into the raw inbox.

This is a connector only: it fetches, unzips, and drops `<activityId>_ACTIVITY.fit`
into the inbox. Import, archive, and idempotency stay with import_garmin_fit.py.

See docs/garmin-personal-api-notes.md for endpoint details and gotchas.
"""

import argparse
import io
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
LIST_PATH = "/activitylist-service/activities/search/activities"
DOWNLOAD_PATH = "/download-service/files/activity/{activity_id}"

PAGE_SIZE = 20
TIMEOUT_SECONDS = 30
MAX_RETRIES = 5
TOKEN_MAX_AGE_SECONDS = 23 * 60 * 60
DOWNLOAD_DELAY_SECONDS = 1.5

DEFAULT_DB_PATH = Path("data_hub.db")
DEFAULT_INBOX = Path("raw/garmin/inbox")
KNOWN_ROOTS = (Path("raw/garmin/inbox"), Path("raw/garmin/archive"), Path("raw/garmin/failed"))
ENV_KEY_NAME = "GARMIN_PERSONAL_API_KEY"


class GarminError(Exception):
    """Raised for failures the user should see. Never includes secrets."""


def load_dotenv(path=Path(".env")):
    """Minimal .env loader. Existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(name.strip(), value)


class GarminClient:
    def __init__(self, api_key, log=None):
        if not api_key:
            raise GarminError(f"{ENV_KEY_NAME} is not set. Add it to .env.")
        self._api_key = api_key
        self._token = None
        self._token_time = 0.0
        self._log = log or (lambda message: None)

    def _send(self, path, headers, method="GET"):
        request = urllib.request.Request(BASE_URL + path, headers=headers, method=method)
        return urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS)

    def _obtain_token(self):
        for attempt in range(MAX_RETRIES + 1):
            try:
                with self._send(
                    TOKEN_PATH,
                    {"Authorization": f"ApiKey {self._api_key}", "Accept": "*/*"},
                    method="POST",
                ) as response:
                    token = response.read().decode("utf-8").strip()
                if not token:
                    raise GarminError("Garmin returned an empty token.")
                self._token = token
                self._token_time = time.monotonic()
                return
            except urllib.error.HTTPError as error:
                if error.code in (401, 403):
                    raise GarminError(
                        f"Garmin rejected the API key (HTTP {error.code}). "
                        "It may have expired; generate a new one in Garmin Connect."
                    ) from None
                if (error.code == 429 or error.code >= 500) and attempt < MAX_RETRIES:
                    self._backoff(attempt, error, "token request")
                    continue
                raise GarminError(f"Garmin token request failed (HTTP {error.code}).") from None
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < MAX_RETRIES:
                    self._backoff(attempt, None, "token request")
                    continue
                raise GarminError(f"Garmin token request failed: {error}") from None

    def _backoff(self, attempt, error, label):
        wait = 5 * 2**attempt
        retry_after = error.headers.get("Retry-After") if error is not None else None
        if retry_after and retry_after.isdigit():
            wait = int(retry_after)
        self._log(f"{label} failed; retrying in {wait}s")
        time.sleep(wait)

    def _request(self, path, accept):
        refreshed = False
        for attempt in range(MAX_RETRIES + 1):
            stale = time.monotonic() - self._token_time >= TOKEN_MAX_AGE_SECONDS
            if self._token is None or stale:
                self._obtain_token()
            try:
                with self._send(
                    path, {"Authorization": f"Bearer {self._token}", "Accept": accept}
                ) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code == 401 and not refreshed:
                    self._token = None
                    refreshed = True
                    continue
                if error.code in (204, 404):
                    return None
                if (error.code == 429 or error.code >= 500) and attempt < MAX_RETRIES:
                    self._backoff(attempt, error, path.split("?")[0])
                    continue
                raise GarminError(f"Garmin request failed for {path.split('?')[0]} (HTTP {error.code}).") from None
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < MAX_RETRIES:
                    self._backoff(attempt, None, path.split("?")[0])
                    continue
                raise GarminError(f"Garmin request failed: {error}") from None
        raise GarminError(f"Garmin request failed after {MAX_RETRIES + 1} attempts.")

    def list_activities(self, start, limit):
        body = self._request(f"{LIST_PATH}?start={start}&limit={limit}", "application/json")
        if body is None:
            return []
        data = json.loads(body)
        if not isinstance(data, list):
            raise GarminError("Garmin returned an unexpected activity list.")
        return data

    def download_zip(self, activity_id):
        # Accept must allow application/x-zip-compressed or */*; application/json returns 406.
        return self._request(DOWNLOAD_PATH.format(activity_id=activity_id), "*/*")


def fit_filename(activity_id):
    return f"{activity_id}_ACTIVITY.fit"


def collect_known_names(roots, db_path):
    """Filenames we already hold on disk or have recorded in the database."""
    known = set()
    for root in roots:
        if root.exists():
            known.update(path.name for path in root.rglob("*.fit"))
    if db_path.exists():
        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                known.update(row[0] for row in connection.execute("SELECT file_name FROM source_files"))
            finally:
                connection.close()
        except sqlite3.Error:
            pass  # database not initialised yet; disk check is enough
    return known


def extract_fit(zip_bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            for entry in archive.infolist():
                if not entry.is_dir() and entry.filename.lower().endswith(".fit"):
                    return archive.read(entry)
    except zipfile.BadZipFile:
        return None
    return None


def looks_like_fit(data):
    return len(data) > 14 and data[8:12] == b".FIT"


def write_atomically(destination, data):
    temporary = destination.with_name(f"{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inbox", default=str(DEFAULT_INBOX), help="Where new FIT files are written.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database used to recognise known files.")
    parser.add_argument("--limit", type=int, default=None, help="Download at most this many new activities.")
    parser.add_argument("--since", default=None, help="Ignore activities older than this local date (YYYY-MM-DD).")
    parser.add_argument("--full", action="store_true", help="Keep paging past fully known pages (backfill).")
    parser.add_argument("--dry-run", action="store_true", help="List what would be downloaded; write nothing.")
    parser.add_argument("--json", action="store_true", help="Print a JSON summary on stdout.")
    return parser.parse_args()


def run(args, log):
    since = None
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d").date()
        except ValueError:
            raise GarminError("--since must look like YYYY-MM-DD.") from None

    inbox = Path(args.inbox)
    known = collect_known_names(KNOWN_ROOTS + (inbox,), Path(args.db))
    client = GarminClient(os.environ.get(ENV_KEY_NAME, "").strip(), log=log)

    summary = {
        "checked": 0,
        "new": 0,
        "downloaded": 0,
        "already_known": 0,
        "no_original_file": 0,
        "failed": 0,
        "dry_run": bool(args.dry_run),
        "files": [],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    if not args.dry_run:
        inbox.mkdir(parents=True, exist_ok=True)

    start = 0
    done = False
    while not done:
        page = client.list_activities(start, PAGE_SIZE)
        if not page:
            break
        page_new = 0
        for activity in page:
            activity_id = activity.get("activityId")
            if not isinstance(activity_id, int) or activity_id <= 0:
                raise GarminError("Garmin returned an invalid activity ID.")
            local_start = str(activity.get("startTimeLocal") or "")
            if since and local_start[:10] and local_start[:10] < since.isoformat():
                done = True
                break
            summary["checked"] += 1
            name = fit_filename(activity_id)
            if name in known:
                summary["already_known"] += 1
                continue
            page_new += 1
            summary["new"] += 1
            if args.limit is not None and summary["new"] > args.limit:
                summary["new"] -= 1
                done = True
                break
            if args.dry_run:
                summary["files"].append(name)
                log(f"would download {name} ({local_start})")
                continue
            zip_bytes = client.download_zip(activity_id)
            fit_bytes = extract_fit(zip_bytes) if zip_bytes else None
            if zip_bytes is None:
                summary["no_original_file"] += 1
                log(f"{name}: Garmin has no original file")
            elif fit_bytes is None or not looks_like_fit(fit_bytes):
                summary["failed"] += 1
                log(f"{name}: download did not contain a valid FIT file")
            else:
                write_atomically(inbox / name, fit_bytes)
                known.add(name)
                summary["downloaded"] += 1
                summary["files"].append(name)
                log(f"saved {name} ({local_start})")
            time.sleep(DOWNLOAD_DELAY_SECONDS)
        if done:
            break
        if len(page) < PAGE_SIZE:
            break
        # Newest first: a page with nothing new means the rest is history we already have.
        if page_new == 0 and not args.full:
            break
        start += PAGE_SIZE

    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    return summary


def main():
    args = parse_args()
    load_dotenv()
    # With --json, stdout is reserved for the summary so callers can parse it.
    log = (lambda message: print(message, file=sys.stderr)) if args.json else print
    try:
        summary = run(args, log)
    except GarminError as error:
        if args.json:
            print(json.dumps({"error": str(error)}))
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary))
    else:
        verb = "would download" if summary["dry_run"] else "downloaded"
        count = summary["new"] if summary["dry_run"] else summary["downloaded"]
        print(
            f"Checked {summary['checked']} activities: {verb} {count}, "
            f"{summary['already_known']} already known, "
            f"{summary['no_original_file']} without an original file, "
            f"{summary['failed']} failed."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
