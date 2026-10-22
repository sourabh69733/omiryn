#!/usr/bin/env python3
"""Build the meaning-search vectors for chats that existed before chat search had them.

New messages are indexed after each background memory run and each upload; this backfills the
rest. Only new or changed chunks are embedded, so running it twice costs nothing the second time.

Dry run by default: lists how many chunks each user would embed. Pass --apply to embed. Only users
who signed up (have a profile) unless --all-users.

    PYTHONPATH=src python scripts/index_chat_embeddings.py --user <id> --apply
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

from agent.memory_engine.search import chat_chunks, index_chat  # noqa: E402
from agent.memory_engine.search.chat_index import embedding_target  # noqa: E402
from storage import get_conversation, init_db, list_conversation_user_ids, list_conversations  # noqa: E402
from storage.chat_embeddings import chunk_hashes  # noqa: E402
from storage.memory_embeddings import embedding_content_hash  # noqa: E402


async def run(args: argparse.Namespace) -> int:
    init_db()
    target = embedding_target()
    if target is None:
        print("MEMORY_EMBEDDING_MODEL is off; nothing to build.")
        return 2
    user_ids = [args.user] if args.user else list_conversation_user_ids(with_profile=not args.all_users)
    total = 0
    for user_id in user_ids:
        pending = 0
        for summary in list_conversations(user_id):
            if summary.get("temporary"):
                continue
            conversation = get_conversation(summary["id"], user_id) or {}
            stored = chunk_hashes(user_id, summary["id"], *target)
            pending += sum(1 for chunk in chat_chunks(list(conversation.get("messages") or [])) if stored.get(chunk[0]) != embedding_content_hash(chunk[3]))
            if args.apply:
                await index_chat(user_id, summary["id"])
        total += pending
        print(f"{user_id}: {pending} chunks {'embedded' if args.apply else 'to embed'}")
    print(f"Total: {total} chunks{'' if args.apply else ' (dry run; pass --apply)'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Embed the chunks.")
    parser.add_argument("--user", help="Only this user id.")
    parser.add_argument("--all-users", action="store_true", help="Include eval and test accounts.")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
