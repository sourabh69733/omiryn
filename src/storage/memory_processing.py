"""Persists private cursors and handoffs for background memory processing."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from security.encryption import decrypt_json, maybe_encrypt_json

from .database import ENGINE
from .schema import agent_conversations, memory_processing_states
from .utils import _isoformat_utc


class MemoryProcessingStateConflictError(RuntimeError):
    """Signals a stale worker or an attempt to move a memory cursor backwards."""


def get_memory_processing_state(conversation_id: str, user_id: str) -> dict[str, Any] | None:
    """Return one user's processing state without exposing another user's record."""
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(memory_processing_states).where(
                memory_processing_states.c.conversation_id == conversation_id,
                memory_processing_states.c.user_id == user_id,
            )
        ).mappings().first()
    return _state_from_row(row) if row else None


def save_memory_processing_state(
    payload: dict[str, Any],
    *,
    expected_version: int,
) -> dict[str, Any]:
    """Create or advance a cursor with optimistic and idempotent batch safety."""
    conversation_id = str(payload["conversation_id"])
    user_id = str(payload["user_id"])
    processed_index = int(payload["processed_through_message_index"])
    batch_key = str(payload.get("last_batch_key") or "").strip() or None
    handoff = payload.get("handoff") or {}

    with ENGINE.begin() as connection:
        _require_owned_conversation(connection, conversation_id, user_id)
        current = connection.execute(
            select(memory_processing_states).where(
                memory_processing_states.c.conversation_id == conversation_id,
                memory_processing_states.c.user_id == user_id,
            )
        ).mappings().first()

        if current is None:
            if expected_version != 0:
                raise MemoryProcessingStateConflictError(
                    "new memory processing state expects version 0"
                )
            connection.execute(
                memory_processing_states.insert().values(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    processed_through_message_index=processed_index,
                    last_batch_key=batch_key,
                    handoff_json=maybe_encrypt_json(user_id, handoff),
                    version=1,
                )
            )
        else:
            current_index = int(current["processed_through_message_index"])
            current_batch_key = current["last_batch_key"]
            if processed_index == current_index and batch_key == current_batch_key:
                return _state_from_row(current)
            if int(current["version"]) != expected_version:
                raise MemoryProcessingStateConflictError("memory processing state version is stale")
            if processed_index <= current_index:
                raise MemoryProcessingStateConflictError("memory processing cursor must move forward")
            result = connection.execute(
                memory_processing_states.update()
                .where(
                    memory_processing_states.c.conversation_id == conversation_id,
                    memory_processing_states.c.user_id == user_id,
                    memory_processing_states.c.version == expected_version,
                )
                .values(
                    processed_through_message_index=processed_index,
                    last_batch_key=batch_key,
                    handoff_json=maybe_encrypt_json(user_id, handoff),
                    version=expected_version + 1,
                    updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                raise MemoryProcessingStateConflictError(
                    "memory processing state changed concurrently"
                )

        row = connection.execute(
            select(memory_processing_states).where(
                memory_processing_states.c.conversation_id == conversation_id,
                memory_processing_states.c.user_id == user_id,
            )
        ).mappings().one()
    return _state_from_row(row)


def _require_owned_conversation(connection, conversation_id: str, user_id: str) -> None:
    found = connection.execute(
        select(agent_conversations.c.id).where(
            agent_conversations.c.id == conversation_id,
            agent_conversations.c.user_id == user_id,
        )
    ).first()
    if not found:
        raise ValueError("conversation was not found for this user")


def _state_from_row(row: Any) -> dict[str, Any]:
    return {
        "conversation_id": row["conversation_id"],
        "user_id": row["user_id"],
        "processed_through_message_index": row["processed_through_message_index"],
        "last_batch_key": row["last_batch_key"],
        "handoff": decrypt_json(row["user_id"], row["handoff_json"]) or {},
        "version": row["version"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }
