"""Gives memories saved before `about` existed their names, so they can be linked too.

Reads only the memories' own sentences, never chats. Run from scripts/data_ops/fill_memory_names.py.
"""

from __future__ import annotations

import json
from typing import Any

from .links import normalize_about

BATCH_SIZE = 40

MEMORY_NAMES_SYSTEM_PROMPT = """You get memories about a user, each with an id and a sentence.
For each one list the specific people, pets, places, companies, groups, works and projects it names,
up to 5, as short names. A sentence that says "their sister" gets her name only when another sentence
here gives it. Use one spelling for one person or thing across all of them; known_names are already in
use. Never the user, nothing generic ("work", "family", "food").
Return JSON: {"names": {"<id>": ["name"]}}. Leave out a memory that names nothing specific."""


def memories_without_names(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        memory
        for memory in memories
        if memory.get("status") == "active" and memory.get("kind") != "procedural" and not memory.get("about")
    ]


async def fill_memory_names(user_id: str, *, apply: bool = False, model: str | None = None) -> dict[str, int]:
    """Counts only, never content. A dry run makes no model call."""
    from agent.providers import write_memory_names
    from storage.memories import list_agent_memories, set_agent_memory_about

    memories = list_agent_memories(user_id)
    missing = memories_without_names(memories)
    counts = {"memories": len(memories), "without_names": len(missing), "named": 0}
    if not apply:
        return counts
    known = sorted({str(name) for memory in memories for name in memory.get("about") or []})
    valid_ids = {str(memory["id"]) for memory in missing}
    for start in range(0, len(missing), BATCH_SIZE):
        batch = missing[start : start + BATCH_SIZE]
        text = json.dumps(
            {
                "known_names": known,
                "memories": [
                    {"id": memory["id"], "sentence": memory.get("statement") or str(memory.get("value"))}
                    for memory in batch
                ],
            },
            ensure_ascii=False,
        )
        raw = await write_memory_names(text, conversation_id=f"fill-names-{user_id}", model=model)
        names = raw.get("names") if isinstance(raw, dict) else None
        for memory_id, about in (names if isinstance(names, dict) else {}).items():
            cleaned = normalize_about(about)
            if cleaned and str(memory_id) in valid_ids and set_agent_memory_about(str(memory_id), user_id, list(cleaned)):
                counts["named"] += 1
                known = sorted({*known, *cleaned})
    return counts


__all__ = ["MEMORY_NAMES_SYSTEM_PROMPT", "fill_memory_names", "memories_without_names"]
