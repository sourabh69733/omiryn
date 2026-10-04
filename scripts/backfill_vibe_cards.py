#!/usr/bin/env python3
"""Write vibe cards for users who chatted before vibe cards existed.

Reads each user's past chats and asks the model for their friend vibe, with the same rules as the
live background step. Dry run by default: prints which areas would be filled. Pass --apply to
write. Users who already have a card are skipped unless --force (then lines are merged). Only users who
signed up (have a profile) are included unless --all-users.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent.cognition.background.vibe_backfill import backfill_user_vibe, recheck_user_vibe  # noqa: E402
from storage import init_db, list_conversation_user_ids  # noqa: E402


async def run(args: argparse.Namespace) -> int:
    init_db()
    user_ids = (
        [args.user] if args.user else list_conversation_user_ids(with_profile=not args.all_users)
    )
    failed = 0
    for user_id in user_ids:
        if args.recheck:
            try:
                checked = await recheck_user_vibe(user_id, apply=args.apply)
            except Exception as error:
                failed += 1
                print(f"{user_id}: error {type(error).__name__}: {str(error)[:200]}")
                continue
            print(
                f"{user_id}: {checked['status']} · milestone {checked['milestone']} · "
                f"kept {', '.join(checked['kept']) or '-'} · dropped {', '.join(checked['dropped']) or '-'}"
            )
            continue
        try:
            result = await backfill_user_vibe(user_id, apply=args.apply, force=args.force)
        except Exception as error:  # one bad user or a provider timeout must not stop the rest
            failed += 1
            print(f"{user_id}: error {type(error).__name__}: {str(error)[:200]}")
            continue
        areas = ", ".join(result["areas"]) or "-"
        print(f"{user_id}: {result['status']} · milestone {result['milestone']} · areas {areas}")
        if args.show:
            for area_id, line in result["areas"].items():
                print(f"    {area_id} ({len(line['evidence'])} msg): {line['text']}")
    if not args.apply:
        print("Dry run. Run again with --apply to write.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the vibe cards.")
    parser.add_argument("--force", action="store_true", help="Also users who already have a card.")
    parser.add_argument("--user", help="Only this user id.")
    parser.add_argument(
        "--all-users", action="store_true", help="Include eval and test accounts (no profile)."
    )
    parser.add_argument("--show", action="store_true", help="Print the lines, not just area names.")
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="Re-prove existing cards instead: drop proof that is gone or does not fit, and lines left without proof.",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
