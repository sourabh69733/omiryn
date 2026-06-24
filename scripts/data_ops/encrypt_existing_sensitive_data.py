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
        description="Encrypt existing plaintext Omiryn conversations and context sources."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing changes.")
    parser.add_argument(
        "--user-id",
        default=None,
        help="Optional user id filter. By default all rows are scanned.",
    )
    args = parser.parse_args()

    import sys

    src_path = str(PROJECT_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    try:
        result = encrypt_existing_sensitive_data(dry_run=args.dry_run, user_id=args.user_id)
    except RuntimeError as error:
        raise SystemExit(str(error)) from error

    print(f"Conversation rows scanned: {result['conversation_scanned']}")
    print(f"Conversation rows encrypted: {result['conversation_encrypted']}")
    print(f"Conversation rows already encrypted: {result['conversation_skipped']}")
    print(f"Context rows scanned: {result['context_scanned']}")
    print(f"Context rows encrypted: {result['context_encrypted']}")
    print(f"Context rows already encrypted: {result['context_skipped']}")
    if args.dry_run:
        print("Dry run only. No database rows were updated.")


def encrypt_existing_sensitive_data(
    *,
    dry_run: bool = False,
    user_id: str | None = None,
) -> dict[str, int]:
    from sqlalchemy import select

    from security.encryption import encryption_enabled, is_encrypted_blob
    from storage import (
        ENGINE,
        _protect_messages,
        _protect_text,
        _unprotect_messages,
        _unprotect_text,
        agent_conversations,
        conversation_context_sources,
        init_db,
    )

    if not encryption_enabled():
        raise RuntimeError(
            "ENCRYPTION_MASTER_KEY is required before encrypting existing sensitive data."
        )

    init_db()

    result = {
        "conversation_scanned": 0,
        "conversation_encrypted": 0,
        "conversation_skipped": 0,
        "context_scanned": 0,
        "context_encrypted": 0,
        "context_skipped": 0,
    }

    with ENGINE.begin() as connection:
        conversation_statement = select(agent_conversations)
        if user_id:
            conversation_statement = conversation_statement.where(
                agent_conversations.c.user_id == user_id
            )
        conversation_rows = connection.execute(conversation_statement).mappings().all()

        for row in conversation_rows:
            result["conversation_scanned"] += 1
            raw_messages = row["messages_json"]
            if is_encrypted_blob(raw_messages):
                result["conversation_skipped"] += 1
                continue
            protected_messages = _protect_messages(
                row["user_id"],
                _unprotect_messages(row["user_id"], raw_messages),
            )
            if not dry_run:
                connection.execute(
                    agent_conversations.update()
                    .where(agent_conversations.c.id == row["id"])
                    .values(messages_json=protected_messages)
                )
            result["conversation_encrypted"] += 1

        context_statement = select(conversation_context_sources)
        if user_id:
            context_statement = context_statement.where(
                conversation_context_sources.c.user_id == user_id
            )
        context_rows = connection.execute(context_statement).mappings().all()

        for row in context_rows:
            result["context_scanned"] += 1
            raw_content = row["content"]
            if _looks_encrypted_context_content(raw_content):
                result["context_skipped"] += 1
                continue
            protected_content = _protect_text(
                row["user_id"],
                _unprotect_text(row["user_id"], raw_content),
            )
            if not dry_run:
                connection.execute(
                    conversation_context_sources.update()
                    .where(conversation_context_sources.c.id == row["id"])
                    .values(content=protected_content)
                )
            result["context_encrypted"] += 1
    return result


def _looks_encrypted_context_content(value: object) -> bool:
    if not isinstance(value, str):
        return is_encrypted_blob(value)
    import json

    stripped = value.strip()
    if not stripped.startswith("{"):
        return False
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return is_encrypted_blob(parsed)


if __name__ == "__main__":
    main()
