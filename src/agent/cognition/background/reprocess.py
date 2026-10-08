"""Runs v3 background cognition over chats an older pipeline already marked as processed.

Chats from the v2 days have a cursor at their last message, so v3 never looks at them and they
have no V3 memories, user card lines, vibe lines or session log. This resets the cursor and runs
v3 batch by batch.
"""

from __future__ import annotations

from typing import Any

from agent.memory_engine.processing import get_processing_state
from storage import list_conversations, reset_memory_processing_state
from storage.profile_facts import list_data_point_extraction_debug

from .service import has_pending_background_cognition, run_background_cognition

V3_EXTRACTOR = "background_cognition_v3"
# One run handles one bounded batch; a long chat needs several.
MAX_BATCHES_PER_CHAT = 60


def chats_needing_v3(user_id: str) -> list[dict[str, Any]]:
    """Chats with a processing cursor but no v3 run on record."""
    v3_chats = {
        row.get("source_id")
        for row in list_data_point_extraction_debug(user_id=user_id, limit=5000)
        if (row.get("metadata") or {}).get("extractor") == V3_EXTRACTOR
    }
    needing = []
    for conversation in list_conversations(user_id):
        if conversation.get("temporary"):
            continue
        state = get_processing_state(conversation["id"], user_id)
        if state and state.processed_through_message_index >= 0 and conversation["id"] not in v3_chats:
            needing.append(conversation)
    return needing


async def reprocess_conversation(
    conversation: dict[str, Any],
    user_id: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """{"status", "batches", "memories_applied", "statuses"}. Writes only with apply=True."""
    messages = list(conversation.get("messages") or [])
    if not apply:
        return {"status": "would_reprocess", "batches": 0, "memories_applied": 0, "statuses": []}
    reset_memory_processing_state(conversation["id"], user_id)
    statuses: list[str] = []
    applied = 0
    for _ in range(MAX_BATCHES_PER_CHAT):
        if not has_pending_background_cognition(conversation["id"], user_id, messages):
            break
        result = await run_background_cognition(
            conversation["id"], user_id, messages, conversation.get("agent_model")
        )
        statuses.append(str(result.get("status")))
        applied += int(result.get("applied_count") or 0)
        if result.get("status") in {"live_error", "live_invalid", "already_processing"}:
            # Provider trouble or another worker on this chat: stop; a rerun or the catch-up
            # continues from where this left off. (A skipped batch moves on by itself.)
            break
    done = not has_pending_background_cognition(conversation["id"], user_id, messages)
    return {
        "status": "done" if done else "partial",
        "batches": len(statuses),
        "memories_applied": applied,
        "statuses": statuses,
    }


__all__ = ["chats_needing_v3", "reprocess_conversation"]
