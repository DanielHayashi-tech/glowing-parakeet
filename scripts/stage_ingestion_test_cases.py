#!/usr/bin/env python3
"""
Stage ingestion test cases into the Garmin inbox.

This script copies existing archived FIT files back into inbox so the UI and
preview/import flow can be tested safely and repeatedly.

Examples:
    python scripts/stage_ingestion_test_cases.py --case wrong-folder-date
    python scripts/stage_ingestion_test_cases.py --case duplicate-known
    python scripts/stage_ingestion_test_cases.py --case mixed-day
    python scripts/stage_ingestion_test_cases.py --case all
"""

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = ROOT / "raw" / "garmin" / "archive"
INBOX_ROOT = ROOT / "raw" / "garmin" / "inbox"


def ensure_directory(path):
    path.mkdir(parents=True, exist_ok=True)


def safe_copy(source_path, target_path):
    ensure_directory(target_path.parent)
    candidate = target_path
    suffix = 1
    while candidate.exists():
        candidate = candidate.with_name(
            f"{target_path.stem}_{suffix}{target_path.suffix}"
        )
        suffix += 1
    shutil.copy2(source_path, candidate)
    return candidate


def require_file(relative_path):
    path = ARCHIVE_ROOT / relative_path
    if not path.exists():
        raise FileNotFoundError(f"Archive file not found: {path}")
    return path


def stage_wrong_folder_date():
    source = require_file(Path("2026-03-02") / "22031296609_ACTIVITY.fit")
    target = INBOX_ROOT / f"03-01-2026__{source.name}"
    return [
        {
            "case": "wrong-folder-date",
            "source": str(source.relative_to(ROOT)),
            "target": str(safe_copy(source, target).relative_to(ROOT)),
            "expectation": "Preview should warn that the inbox date hint does not match the activity date."
        }
    ]


def stage_duplicate_known():
    source = require_file(Path("2026-03-10") / "22132295901_ACTIVITY.fit")
    target = INBOX_ROOT / source.name
    return [
        {
            "case": "duplicate-known",
            "source": str(source.relative_to(ROOT)),
            "target": str(safe_copy(source, target).relative_to(ROOT)),
            "expectation": "Preview should mark this file as already imported."
        }
    ]


def stage_mixed_day():
    staged = []
    scenarios = [
        (Path("2026-03-12") / "22154136150_ACTIVITY.fit", "daymix_run__22154136150_ACTIVITY.fit"),
        (Path("2026-03-12") / "22154399998_ACTIVITY.fit", "daymix_strength__22154399998_ACTIVITY.fit"),
        (Path("2026-03-10") / "22132297404_ACTIVITY.fit", "daymix_run2__22132297404_ACTIVITY.fit"),
        (Path("2026-03-10") / "22132431062_ACTIVITY.fit", "daymix_run3__22132431062_ACTIVITY.fit"),
    ]
    for source_relative, inbox_name in scenarios:
        source = require_file(source_relative)
        target = INBOX_ROOT / inbox_name
        staged.append(
            {
                "case": "mixed-day",
                "source": str(source.relative_to(ROOT)),
                "target": str(safe_copy(source, target).relative_to(ROOT)),
                "expectation": "The staging area should group multiple files under the same detected activity day."
            }
        )
    return staged


CASE_HANDLERS = {
    "wrong-folder-date": stage_wrong_folder_date,
    "duplicate-known": stage_duplicate_known,
    "mixed-day": stage_mixed_day,
}


def parse_args():
    parser = argparse.ArgumentParser(description="Stage Garmin ingestion test cases into inbox.")
    parser.add_argument(
        "--case",
        default="all",
        choices=["all", *CASE_HANDLERS.keys()],
        help="Which test case to stage.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    ensure_directory(INBOX_ROOT)

    selected = CASE_HANDLERS.keys() if args.case == "all" else [args.case]
    staged = []
    for case_name in selected:
        staged.extend(CASE_HANDLERS[case_name]())

    print("Staged test files:")
    for row in staged:
        print(f"- [{row['case']}] {row['target']}")
        print(f"  expectation: {row['expectation']}")


if __name__ == "__main__":
    main()
