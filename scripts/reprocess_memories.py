#!/usr/bin/env python3
"""Run v3 memory processing over chats an older pipeline already handled.

Chats processed by the v2 pipeline are marked as done, so v3 never saw them: no V3 memories,
user card, vibe lines or session log. This resets their cursor and runs v3 over them.

Dry run by default: lists the chats. Pass --apply to process. Only users who signed up (have a
profile) unless --all-users. --conversation forces one chat even if v3 already ran on it.
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

from agent.cognition.background.reprocess import chats_needing_v3, reprocess_conversation  # noqa: E402
from storage import get_conversation, init_db, list_conversation_user_ids  # noqa: E402


async def run(args: argparse.Namespace) -> int:
    init_db()
    if args.conversation:
        if not args.user:
            print("--conversation needs --user.")
            return 2
        conversation = get_conversation(args.conversation, args.user)
        if conversation is None:
            print("Conversation not found for that user.")
            return 2
        work = {args.user: [conversation]}
    else:
        user_ids = [args.user] if args.user else list_conversation_user_ids(with_profile=not args.all_users)
        work = {user_id: chats_needing_v3(user_id) for user_id in user_ids}
    failed = 0
    for user_id, conversations in work.items():
        for conversation in conversations:
            count = len(conversation.get("messages") or [])
            try:
                result = await reprocess_conversation(conversation, user_id, apply=args.apply)
            except Exception as error:  # one chat must not stop the rest
                failed += 1
                print(f"{user_id} {conversation['id']}: error {type(error).__name__}: {str(error)[:200]}")
                continue
            print(
                f"{user_id} {conversation['id']} ({count} messages): {result['status']}"
                f" · batches {result['batches']} · memories {result['memories_applied']}"
            )
    if not any(work.values()):
        print("No chats need reprocessing.")
    elif not args.apply:
        print("Dry run. Run again with --apply to process.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Process the chats.")
    parser.add_argument("--user", help="Only this user id.")
    parser.add_argument("--conversation", help="Force this chat (needs --user).")
    parser.add_argument("--all-users", action="store_true", help="Include eval and test accounts.")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
