#!/usr/bin/env python3
"""Set memory evidence times to when the user sent the message (older rows used extraction time).

Dry run by default: prints what would change. Pass --apply to write. Safe to re-run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from storage.evidence_backfill import backfill_evidence_times  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the corrected times.")
    args = parser.parse_args()
    counts = backfill_evidence_times(apply=args.apply)
    verb = "Fixed" if args.apply else "Would fix"
    print(
        f"{counts['checked']} evidence rows: {verb.lower()} {counts['fixed']}, "
        f"{counts['already_right']} already right, {counts['quote_mismatch']} skipped (quote does "
        f"not match the message), {counts['no_message_time']} skipped (no message time)."
    )
    if not args.apply and counts["fixed"]:
        print("Run again with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
