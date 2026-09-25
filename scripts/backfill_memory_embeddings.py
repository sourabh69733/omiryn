#!/usr/bin/env python3
"""Embed active v3 memories that have no vector for the configured model, or whose text changed.

Background cognition embeds new memories and heals a few failed ones per batch, so this is for
bulk catch-up (a new model, memories saved before semantic recall). Safe to re-run: memories
whose vector matches their current text are skipped. --prune-orphans also deletes vectors and
reviews of memories that no longer exist.
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
    memories_needing_embeddings,
    memory_embedding_target,
)
from storage.database import ENGINE  # noqa: E402
from storage.memories import list_agent_memories  # noqa: E402
from storage.memory_embeddings import prune_orphan_memory_rows  # noqa: E402
from storage.schema import agent_memories  # noqa: E402

BATCH_SIZE = 64


async def _backfill(dry_run: bool, prune_orphans: bool) -> int:
    if prune_orphans and not dry_run:
        print(f"Pruned orphan rows: {prune_orphan_memory_rows()}")
    target = memory_embedding_target()
    if target is None:
        print("Semantic recall is disabled (MEMORY_EMBEDDING_MODEL=off); nothing to do.")
        return 0
    provider, model = target
    with ENGINE.begin() as connection:
        user_ids = [row[0] for row in connection.execute(select(agent_memories.c.user_id).distinct())]
    indexed = 0
    total_active = up_to_date = 0
    for user_id in user_ids:
        memories = [m for m in list_agent_memories(user_id) if m.get("status") == "active"]
        missing = memories_needing_embeddings(memories, provider, model)
        total_active += len(memories)
        up_to_date += len(memories) - len(missing)
        if dry_run:
            if memories:
                print(f"user {user_id}: {len(memories)} active, {len(missing)} to embed")
            indexed += len(missing)
            continue
        for start in range(0, len(missing), BATCH_SIZE):
            indexed += await index_agent_memories(missing[start : start + BATCH_SIZE])
    print(
        f"{len(user_ids)} users, {total_active} active memories, {up_to_date} up to date "
        f"with {provider}:{model}."
    )
    print(f"{'Would embed' if dry_run else 'Embedded'} {indexed} memories.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Only count what would be embedded.")
    parser.add_argument(
        "--prune-orphans", action="store_true", help="Also delete vectors and reviews of deleted memories."
    )
    args = parser.parse_args()
    return asyncio.run(_backfill(args.dry_run, args.prune_orphans))


if __name__ == "__main__":
    raise SystemExit(main())
