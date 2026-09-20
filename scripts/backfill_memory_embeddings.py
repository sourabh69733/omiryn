#!/usr/bin/env python3
"""Embed existing active v3 memories that have no vector for the configured model.

Indexing normally happens when background cognition writes memories, so memories saved
before semantic recall was enabled need this one-time pass. Safe to re-run: memories that
already have a vector for the configured provider/model are skipped.
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

from sqlalchemy import select  # noqa: E402

from agent.memory_engine.memories.embeddings import (  # noqa: E402
    index_agent_memories,
    memory_embedding_target,
)
from storage.database import ENGINE  # noqa: E402
from storage.memories import list_agent_memories  # noqa: E402
from storage.memory_embeddings import list_agent_memory_embeddings  # noqa: E402
from storage.schema import agent_memories  # noqa: E402

BATCH_SIZE = 64


async def _backfill(dry_run: bool) -> int:
    target = memory_embedding_target()
    if target is None:
        print("Semantic recall is disabled (MEMORY_EMBEDDING_MODEL=off); nothing to do.")
        return 0
    provider, model = target
    with ENGINE.begin() as connection:
        user_ids = [row[0] for row in connection.execute(select(agent_memories.c.user_id).distinct())]
    indexed = 0
    total_active = already_embedded = 0
    for user_id in user_ids:
        memories = [m for m in list_agent_memories(user_id) if m.get("status") == "active"]
        have = {
            str(item["memory_id"])
            for item in list_agent_memory_embeddings(user_id, [str(m["id"]) for m in memories])
            if item.get("provider") == provider and item.get("model") == model
        }
        missing = [m for m in memories if str(m["id"]) not in have]
        total_active += len(memories)
        already_embedded += len(have)
        if dry_run:
            if memories:
                print(f"user {user_id}: {len(memories)} active, {len(missing)} to embed")
            indexed += len(missing)
            continue
        for start in range(0, len(missing), BATCH_SIZE):
            indexed += await index_agent_memories(missing[start : start + BATCH_SIZE])
    print(
        f"{len(user_ids)} users, {total_active} active memories, {already_embedded} already "
        f"embedded with {provider}:{model}."
    )
    print(f"{'Would embed' if dry_run else 'Embedded'} {indexed} memories.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Only count what would be embedded.")
    return asyncio.run(_backfill(parser.parse_args().dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
