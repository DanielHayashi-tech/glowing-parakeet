#!/usr/bin/env python3
"""
Reset local development state for the Garmin ingestion pipeline.

Default behavior:
- delete the SQLite database
- clear archive files
- clear failed files
- preserve inbox contents

Examples:
    python scripts/reset_dev_state.py
    python scripts/reset_dev_state.py --clear-inbox
"""

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data_hub.db"
INBOX_ROOT = ROOT / "raw" / "garmin" / "inbox"
ARCHIVE_ROOT = ROOT / "raw" / "garmin" / "archive"
FAILED_ROOT = ROOT / "raw" / "garmin" / "failed"


def ensure_directory(path):
    path.mkdir(parents=True, exist_ok=True)


def clear_directory_contents(root):
    ensure_directory(root)
    for child in root.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def write_gitkeep(root):
    ensure_directory(root)
    gitkeep = root / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Reset local Garmin dev state.")
    parser.add_argument(
        "--clear-inbox",
        action="store_true",
        help="Also clear inbox files. By default inbox is preserved.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Deleted database: {DB_PATH.relative_to(ROOT)}")
    else:
        print(f"Database already absent: {DB_PATH.relative_to(ROOT)}")

    clear_directory_contents(ARCHIVE_ROOT)
    write_gitkeep(ARCHIVE_ROOT)
    print(f"Cleared archive: {ARCHIVE_ROOT.relative_to(ROOT)}")

    clear_directory_contents(FAILED_ROOT)
    write_gitkeep(FAILED_ROOT)
    print(f"Cleared failed: {FAILED_ROOT.relative_to(ROOT)}")

    if args.clear_inbox:
        clear_directory_contents(INBOX_ROOT)
        write_gitkeep(INBOX_ROOT)
        print(f"Cleared inbox: {INBOX_ROOT.relative_to(ROOT)}")
    else:
        ensure_directory(INBOX_ROOT)
        write_gitkeep(INBOX_ROOT)
        print(f"Preserved inbox: {INBOX_ROOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
