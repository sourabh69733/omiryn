#!/usr/bin/env python
"""Give one user's older memories their names (who or what each is about), so they can be linked.

Dry run by default: prints counts only and calls no model. --apply calls the model (small cost) and
saves the names. Reads the memories' own sentences, never chats, and never prints their content.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent.cognition.background.uploads.read import upload_model  # noqa: E402
from agent.memory_engine.memories.fill_names import fill_memory_names  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--apply", action="store_true", help="Call the model and save (default: dry run).")
    args = parser.parse_args()
    counts = asyncio.run(fill_memory_names(args.user_id, apply=args.apply, model=upload_model()))
    print(f"{counts['memories']} memories, {counts['without_names']} without names, {counts['named']} named now")
    if not args.apply:
        print("Dry run. Run again with --apply.")


if __name__ == "__main__":
    main()
