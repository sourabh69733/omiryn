"""Things Omi knows that the message does not touch but the moment might suit, rotated across replies."""

from __future__ import annotations

from typing import Any

from agent.memory_engine.memories.retrieval import might_fit_memories
from agent.shared.timeline import user_zone
from storage import get_user_timezone, list_agent_context_snapshots

from .memories import memory_sentence, memory_time_note

MIGHT_FIT_SOURCE_TYPE = "might_fit"
# A memory offered as "might fit" waits this many replies before it is offered again.
MIGHT_FIT_ROTATION_REPLIES = 5


def might_fit_sources(
    conversation_id: str,
    user_id: str | None,
    memory_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Things Omi knows that the message does not touch but the moment might suit."""
    if not user_id:
        return []
    shown = {
        str(memory_id)
        for source in memory_sources
        for memory_id in (source.get("metadata") or {}).get("memory_ids") or []
    }
    memories = might_fit_memories(
        user_id,
        exclude_ids=shown,
        recently_offered=_recently_offered(conversation_id, user_id),
    )
    if not memories:
        return []
    zone = user_zone(get_user_timezone(user_id))
    lines = [
        "Things you know about them that this message does not touch. Use at most one, only if it "
        "fits the moment naturally (a quiet or open turn); their message comes first. Never list them.",
        *(f"- {memory_sentence(memory)}{memory_time_note(memory, zone)}" for memory in memories),
    ]
    return [
        {
            "source_type": MIGHT_FIT_SOURCE_TYPE,
            "title": "Might fit",
            "content": "\n".join(lines),
            "metadata": {"memory_ids": [memory.get("id") for memory in memories]},
        }
    ]


def _recently_offered(conversation_id: str, user_id: str) -> set[str]:
    offered: set[str] = set()
    for snapshot in list_agent_context_snapshots(
        conversation_id, user_id, limit=MIGHT_FIT_ROTATION_REPLIES
    ):
        for source in (snapshot.get("context") or {}).get("sources") or []:
            if source.get("source_type") == MIGHT_FIT_SOURCE_TYPE:
                offered.update(str(item) for item in (source.get("metadata") or {}).get("memory_ids") or [])
    return offered


__all__ = ["MIGHT_FIT_ROTATION_REPLIES", "MIGHT_FIT_SOURCE_TYPE", "might_fit_sources"]
