"""Deletes chosen messages from a chat, and what Omi learned only from them.

A deleted message stays as an empty placeholder at its position: memory and vibe proof, the
background cursor, feedback and notes point at messages by position, so removing it would make
every later link point at the wrong message. Its text is gone; the app hides it and the model
never sees it.

What points at a message is removed exactly (memory and vibe proof, Omi's notes, open questions,
ratings); memories left with no proof go. What summarizes the whole chat (chat summary, session
log, topics) cannot be edited line by line, so it is cleared and rebuilt by a fresh background
run over the remaining messages.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from agent.shared.clock import utc_now_iso

from .conversation_threads import _delete_threads_only_from
from .conversations import forget_memory_evidence, get_conversation, save_conversation
from .database import ENGINE
from .schema import (
    agent_memories,
    agent_memory_evidence,
    agent_message_feedback,
    agent_open_questions,
    agent_self_notes,
    conversation_states,
    data_point_extraction_debug,
    memory_batch_failures,
    memory_operation_applications,
    memory_processing_leases,
    memory_processing_states,
    thread_operation_applications,
)
from .utils import _require_user_id
from .vibe_cards import drop_vibe_proof_from_conversation, vibe_deletion_impact


class MessageDeletionError(ValueError):
    """The chat or one of the messages cannot be deleted."""


def message_deletion_impact(user_id: str, conversation_id: str, message_indexes: list[int]) -> dict[str, Any]:
    """What deleting these messages also removes, for the confirm dialog."""
    owner_id = _require_user_id(user_id, "message deletion")
    indexes = _valid_indexes(owner_id, conversation_id, message_indexes)
    vibe = vibe_deletion_impact(owner_id, conversation_id, indexes)
    return {
        "message_count": len(indexes),
        "memories_forgotten": _memories_only_from(owner_id, conversation_id, indexes),
        "vibe_removed": vibe["removed"],
        "vibe_weakened": vibe["weakened"],
    }


def delete_conversation_messages(user_id: str, conversation_id: str, message_indexes: list[int]) -> dict[str, Any]:
    """Blank the messages and remove what came only from them; returns what was removed."""
    owner_id = _require_user_id(user_id, "message deletion")
    impact = message_deletion_impact(owner_id, conversation_id, message_indexes)
    indexes = _valid_indexes(owner_id, conversation_id, message_indexes)
    conversation = get_conversation(conversation_id, owner_id) or {}
    messages = list(conversation.get("messages") or [])
    deleted_at = utc_now_iso()
    chosen = set(indexes)
    for position, message in enumerate(messages):
        # A reply keeps pointing at the deleted message, but no longer quotes it.
        reply_to = message.get("reply_to")
        if isinstance(reply_to, dict) and reply_to.get("index") in chosen:
            messages[position] = {**message, "reply_to": {"index": reply_to["index"], "deleted": True}}
    for index in indexes:
        original = messages[index]
        messages[index] = {
            "role": original.get("role"),
            "content": "",
            "deleted": True,
            "deleted_at": deleted_at,
            **({"created_at": original["created_at"]} if original.get("created_at") else {}),
        }
    save_conversation({**conversation, "messages": messages}, owner_id)

    with ENGINE.begin() as connection:
        forget_memory_evidence(connection, owner_id, conversation_id, set(indexes))
        for table in (agent_self_notes, agent_open_questions, agent_message_feedback):
            connection.execute(
                table.delete().where(
                    table.c.user_id == owner_id,
                    table.c.conversation_id == conversation_id,
                    table.c.message_index.in_(indexes),
                )
            )
        # Whole-chat summaries are rebuilt from what is left: clear them and the cursor.
        _delete_threads_only_from(connection, owner_id, {conversation_id})
        for table in (
            conversation_states,
            thread_operation_applications,
            memory_operation_applications,
            memory_processing_states,
            memory_processing_leases,
            memory_batch_failures,
        ):
            connection.execute(
                table.delete().where(table.c.user_id == owner_id, table.c.conversation_id == conversation_id)
            )
        connection.execute(
            data_point_extraction_debug.delete().where(
                data_point_extraction_debug.c.user_id == owner_id,
                data_point_extraction_debug.c.source_id == conversation_id,
            )
        )
    drop_vibe_proof_from_conversation(owner_id, conversation_id, set(indexes))
    return {**impact, "message_indexes": indexes}


def _valid_indexes(owner_id: str, conversation_id: str, message_indexes: list[int]) -> list[int]:
    conversation = get_conversation(conversation_id, owner_id)
    if conversation is None:
        raise MessageDeletionError("Conversation not found.")
    messages = conversation.get("messages") or []
    indexes = sorted({int(index) for index in message_indexes})
    if not indexes:
        raise MessageDeletionError("Choose at least one message.")
    if any(index < 0 or index >= len(messages) for index in indexes):
        raise MessageDeletionError("Message not found.")
    return [index for index in indexes if not messages[index].get("deleted")]


def _memories_only_from(owner_id: str, conversation_id: str, indexes: list[int]) -> int:
    if not indexes:
        return 0
    chosen = (
        (agent_memory_evidence.c.conversation_id == conversation_id)
        & agent_memory_evidence.c.message_index.in_(indexes)
    )
    touched = select(agent_memory_evidence.c.memory_id).where(agent_memory_evidence.c.user_id == owner_id, chosen)
    elsewhere = select(agent_memory_evidence.c.memory_id).where(agent_memory_evidence.c.user_id == owner_id, ~chosen)
    with ENGINE.begin() as connection:
        return int(
            connection.execute(
                select(func.count()).select_from(agent_memories).where(
                    agent_memories.c.user_id == owner_id,
                    agent_memories.c.status == "active",
                    agent_memories.c.id.in_(touched),
                    ~agent_memories.c.id.in_(elsewhere),
                )
            ).scalar_one()
        )


__all__ = ["MessageDeletionError", "delete_conversation_messages", "message_deletion_impact"]
