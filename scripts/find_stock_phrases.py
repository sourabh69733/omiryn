#!/usr/bin/env python3
"""Find companion lines repeated across many different chats: stock lines that fit any message.

Prints what it finds; --write adds them to the reviewable list in
src/agent/context_engine/conversation_engine/policy/stock_phrases.json, which the reply check
and the evals read. Only counts are computed; user messages are never read into the list.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import select  # noqa: E402

from agent.context_engine.conversation_engine.policy.stock_phrases import (  # noqa: E402
    DEFAULT_MIN_CONVERSATIONS,
    STOCK_PHRASES,
    find_stock_lines,
    save_learned_phrases,
)
from storage import get_conversation  # noqa: E402
from storage.database import ENGINE  # noqa: E402
from storage.schema import agent_conversations  # noqa: E402


def _all_conversations():
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(agent_conversations.c.id, agent_conversations.c.user_id)
        ).all()
    for conversation_id, user_id in rows:
        conversation = get_conversation(conversation_id, user_id)
        if conversation:
            yield conversation.get("messages") or []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-conversations",
        type=int,
        default=DEFAULT_MIN_CONVERSATIONS,
        help="A line must appear in at least this many different chats.",
    )
    parser.add_argument("--write", action="store_true", help="Add new lines to the learned list.")
    args = parser.parse_args()
    found = find_stock_lines(_all_conversations(), min_conversations=args.min_conversations)
    new = [(line, count) for line, count in found if not any(p in line for p in STOCK_PHRASES)]
    print(f"{len(found)} repeated lines, {len(new)} not yet covered:")
    for line, count in new:
        print(f"  {count:4d} chats  {line}")
    if args.write and new:
        total = save_learned_phrases(line for line, _count in new)
        print(f"Saved; the learned list now has {len(total)} lines. Review the diff before committing.")
    elif new:
        print("Run again with --write to add them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
