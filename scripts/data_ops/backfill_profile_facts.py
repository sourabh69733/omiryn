#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if load_dotenv:
        load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Backfill Omiryn profile facts from existing agent conversations."
    )
    parser.add_argument("--user-id", required=True, help="Supabase auth user UUID.")
    parser.add_argument(
        "--conversation-id",
        default=None,
        help="Optional single conversation id to backfill.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing facts.")
    args = parser.parse_args()

    import sys

    src_path = str(PROJECT_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    from agent.memory_engine.profile_facts import extract_profile_facts_from_message
    from agent.runtime.providers import assess_user_message_quality
    from storage import get_conversation, init_db, list_conversations, upsert_profile_fact

    init_db()

    if args.conversation_id:
        conversation = get_conversation(args.conversation_id, args.user_id)
        conversations = [conversation] if conversation else []
    else:
        conversations = list_conversations(args.user_id)

    if not conversations:
        print("No conversations found for this user.")
        return

    extracted_count = 0
    written_count = 0
    skipped_count = 0

    for conversation in conversations:
        conversation_id = conversation["id"]
        messages = conversation.get("messages") or []
        for index, message in enumerate(messages):
            if message.get("role") != "user":
                continue
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            if not assess_user_message_quality(messages[: index + 1])["valid"]:
                skipped_count += 1
                continue

            facts = extract_profile_facts_from_message(
                args.user_id,
                conversation_id,
                content,
                index,
            )
            extracted_count += len(facts)
            if not args.dry_run:
                for fact in facts:
                    upsert_profile_fact(fact)
                    written_count += 1

    print(f"Conversations scanned: {len(conversations)}")
    print(f"Low-quality user messages skipped: {skipped_count}")
    print(f"Facts extracted: {extracted_count}")
    if args.dry_run:
        print("Dry run only. No profile facts were written.")
    else:
        print(f"Profile fact upserts attempted: {written_count}")


if __name__ == "__main__":
    main()
