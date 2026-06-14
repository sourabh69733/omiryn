from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    load_dotenv = None

if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")

from storage import database_url, init_db, reset_db


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset Omiryn local runtime data: conversations, context, drafts, and usage logs.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive reset.",
    )
    parser.add_argument(
        "--show-db",
        action="store_true",
        help="Print the configured database URL before resetting.",
    )
    args = parser.parse_args()

    if args.show_db:
        print(f"DATABASE_URL={database_url()}")

    if not args.yes:
        print("Refusing to reset data without --yes.")
        print("Run: ./scripts/reset-data.sh --yes")
        return 2

    reset_db()
    init_db()
    print("Omiryn runtime data reset.")
    print("Cleared: conversations, imported context, drafts, and usage logs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
