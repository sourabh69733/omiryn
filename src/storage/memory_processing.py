"""Persists private cursors and handoffs for background memory processing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from security.encryption import decrypt_json, maybe_encrypt_json

from .database import ENGINE
from .schema import (
    memory_batch_failures,
    agent_conversations,
    memory_processing_leases,
    memory_processing_states,
)
from .utils import _isoformat_utc


class MemoryProcessingStateConflictError(RuntimeError):
    """Signals a stale worker or an attempt to move a memory cursor backwards."""


def claim_memory_processing_batch(
    conversation_id: str,
    user_id: str,
    batch_key: str,
    *,
    expected_processed_index: int,
    lease_seconds: float,
) -> str | None:
    """Atomically claim one batch, returning an owner token only to the winner."""
    if not conversation_id or not user_id or not batch_key:
        raise ValueError("memory processing lease requires conversation, user, and batch")
    if lease_seconds <= 0:
        raise ValueError("memory processing lease duration must be positive")

    owner_token = str(uuid4())
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=lease_seconds)
    try:
        with ENGINE.begin() as connection:
            _require_owned_conversation(connection, conversation_id, user_id)
            connection.execute(
                memory_processing_leases.insert().values(
                    batch_key=batch_key,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    owner_token=owner_token,
                    expires_at=expires_at,
                )
            )
            if not _cursor_matches(
                connection,
                conversation_id,
                user_id,
                expected_processed_index,
            ):
                _release_lease(connection, batch_key, user_id, owner_token)
                return None
        return owner_token
    except IntegrityError:
        pass

    with ENGINE.begin() as connection:
        _require_owned_conversation(connection, conversation_id, user_id)
        current = connection.execute(
            select(memory_processing_leases).where(
                memory_processing_leases.c.batch_key == batch_key,
                memory_processing_leases.c.conversation_id == conversation_id,
                memory_processing_leases.c.user_id == user_id,
            )
        ).mappings().first()
        if current is None:
            return None
        result = connection.execute(
            memory_processing_leases.update()
            .where(
                memory_processing_leases.c.batch_key == batch_key,
                memory_processing_leases.c.owner_token == current["owner_token"],
                memory_processing_leases.c.expires_at <= now,
            )
            .values(
                owner_token=owner_token,
                expires_at=expires_at,
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            return None
        if not _cursor_matches(
            connection,
            conversation_id,
            user_id,
            expected_processed_index,
        ):
            _release_lease(connection, batch_key, user_id, owner_token)
            return None
    return owner_token


def release_memory_processing_batch(
    batch_key: str,
    user_id: str,
    owner_token: str,
) -> bool:
    """Release only the lease still owned by this worker."""
    if not batch_key or not user_id or not owner_token:
        return False
    with ENGINE.begin() as connection:
        return _release_lease(connection, batch_key, user_id, owner_token)


def _cursor_matches(
    connection: Any,
    conversation_id: str,
    user_id: str,
    expected_processed_index: int,
) -> bool:
    current_index = connection.execute(
        select(memory_processing_states.c.processed_through_message_index).where(
            memory_processing_states.c.conversation_id == conversation_id,
            memory_processing_states.c.user_id == user_id,
        )
    ).scalar_one_or_none()
    actual_index = int(current_index) if current_index is not None else -1
    return actual_index == expected_processed_index


def _release_lease(
    connection: Any,
    batch_key: str,
    user_id: str,
    owner_token: str,
) -> bool:
    result = connection.execute(
        memory_processing_leases.delete().where(
            memory_processing_leases.c.batch_key == batch_key,
            memory_processing_leases.c.user_id == user_id,
            memory_processing_leases.c.owner_token == owner_token,
        )
    )
    return result.rowcount == 1


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


def reset_memory_processing_state(conversation_id: str, user_id: str) -> None:
    """Forget how far background cognition got in one chat, so it is processed again.

    Only for maintenance (reprocessing chats handled by an older pipeline). Saved memories,
    vibe lines and threads stay; the rerun reinforces what it finds again instead of copying it.
    """
    with ENGINE.begin() as connection:
        _require_owned_conversation(connection, conversation_id, user_id)
        for table in (memory_processing_states, memory_processing_leases):
            connection.execute(
                table.delete().where(
                    table.c.conversation_id == conversation_id,
                    table.c.user_id == user_id,
                )
            )


def record_memory_batch_failure(
    batch_key: str,
    conversation_id: str,
    user_id: str,
    error: str,
) -> int:
    """Count one content failure for this batch; returns how many it has had."""
    with ENGINE.begin() as connection:
        current = connection.execute(
            select(memory_batch_failures.c.attempts).where(
                memory_batch_failures.c.batch_key == batch_key,
                memory_batch_failures.c.user_id == user_id,
            )
        ).scalar_one_or_none()
        attempts = int(current or 0) + 1
        values = {"attempts": attempts, "last_error": error[:500], "updated_at": func.now()}
        if current is None:
            connection.execute(
                memory_batch_failures.insert().values(
                    batch_key=batch_key, conversation_id=conversation_id, user_id=user_id, **values
                )
            )
        else:
            connection.execute(
                memory_batch_failures.update()
                .where(memory_batch_failures.c.batch_key == batch_key)
                .values(**values)
            )
    return attempts


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
