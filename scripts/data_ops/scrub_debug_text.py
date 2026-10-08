#!/usr/bin/env python
"""Remove chat text left in older debug records (context snapshots, trace steps, background debug).

Dry run by default: prints how many rows would change, never their content. --apply rewrites them.
Back up the database first; the removed text cannot be restored.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from storage.debug_scrub import DEFAULT_KEEP_DAYS, scrub_debug_records  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Rewrite the rows (default: dry run).")
    parser.add_argument(
        "--keep-days",
        type=int,
        default=DEFAULT_KEEP_DAYS,
        help=f"Leave background debug rows newer than this whole (default {DEFAULT_KEEP_DAYS}).",
    )
    args = parser.parse_args()
    counts = scrub_debug_records(apply=args.apply, keep_days=args.keep_days)
    verb = "Rewrote" if args.apply else "Would rewrite"
    for table, count in counts.items():
        print(f"{verb} {count} {table.replace('_', ' ')} rows")
    if not args.apply:
        print("Dry run. Back up the database, then run again with --apply.")


if __name__ == "__main__":
    main()
