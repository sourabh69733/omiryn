"""Persists encrypted conversation threads and optimistic per-session state records."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from .database import ENGINE
from .schema import (
    agent_conversations,
    conversation_states,
    conversation_threads,
    thread_operation_applications,
)
from .utils import _isoformat_utc, _protect_text, _require_user_id, _unprotect_text


class ConversationStateConflictError(RuntimeError):
    """Signals a stale optimistic version or backwards state update."""


def _insert_conversation_thread(payload: dict[str, Any]) -> dict[str, Any]:
    owner_id = str(payload["user_id"])
    with ENGINE.begin() as connection:
        _require_owned_conversation(connection, payload["created_in_conversation_id"], owner_id)
        _require_owned_conversation(connection, payload["last_conversation_id"], owner_id)
        values = _protected_thread_values(payload, owner_id)
        connection.execute(conversation_threads.insert().values(**values))
        row = connection.execute(
            select(conversation_threads).where(conversation_threads.c.id == payload["id"])
        ).mappings().one()
    return _thread_from_row(row)


def _get_conversation_thread(thread_id: str, user_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(conversation_threads).where(
                conversation_threads.c.id == thread_id,
                conversation_threads.c.user_id == user_id,
            )
        ).mappings().first()
    return _thread_from_row(row) if row else None


def _list_conversation_threads(
    user_id: str,
    *,
    statuses: tuple[str, ...] | None = None,
    conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(conversation_threads).where(
        conversation_threads.c.user_id == user_id
    )
    if statuses:
        statement = statement.where(conversation_threads.c.status.in_(statuses))
    if conversation_id:
        statement = statement.where(
            conversation_threads.c.last_conversation_id == conversation_id
        )
    statement = statement.order_by(conversation_threads.c.updated_at.desc())
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_thread_from_row(row) for row in rows]


def _update_conversation_thread(
    thread_id: str,
    user_id: str,
    changes: dict[str, Any],
    *,
    expected_version: int,
) -> dict[str, Any]:
    with ENGINE.begin() as connection:
        current = connection.execute(
            select(conversation_threads).where(
                conversation_threads.c.id == thread_id,
                conversation_threads.c.user_id == user_id,
            )
        ).mappings().first()
        if not current:
            raise ValueError("conversation thread was not found for this user")
        if int(current["version"]) != expected_version:
            raise ConversationStateConflictError("conversation thread version is stale")
        if changes.get("last_conversation_id"):
            _require_owned_conversation(connection, changes["last_conversation_id"], user_id)
        if changes.get("status") in {"paused", "completed", "blocked_by_user"}:
            active_state = connection.execute(
                select(conversation_states.c.conversation_id).where(
                    conversation_states.c.user_id == user_id,
                    conversation_states.c.active_thread_id == thread_id,
                )
            ).first()
            if active_state:
                raise ValueError("clear the active thread pointer before closing or pausing it")

        values = _protected_thread_values(changes, user_id)
        values.update(version=expected_version + 1, updated_at=func.now())
        result = connection.execute(
            conversation_threads.update()
            .where(
                conversation_threads.c.id == thread_id,
                conversation_threads.c.user_id == user_id,
                conversation_threads.c.version == expected_version,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise ConversationStateConflictError("conversation thread changed concurrently")
        row = connection.execute(
            select(conversation_threads).where(conversation_threads.c.id == thread_id)
        ).mappings().one()
    return _thread_from_row(row)


def threads_only_from_conversation(user_id: str, conversation_id: str) -> list[dict[str, Any]]:
    """Threads that started and last ran in this chat, so deleting the chat takes them."""
    owner_id = _require_user_id(user_id, "conversation thread list")
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(conversation_threads).where(_only_from(owner_id, {conversation_id}))
        ).mappings().all()
    return [_thread_from_row(row) for row in rows]


def _delete_threads_only_from(connection, user_id: str, conversation_ids: set[str]) -> int:
    """Delete threads whose chats are all gone, and anything that still points at them."""
    thread_ids = list(
        connection.execute(
            select(conversation_threads.c.id).where(_only_from(user_id, conversation_ids))
        ).scalars().all()
    )
    if not thread_ids:
        return 0
    connection.execute(
        conversation_states.update()
        .where(
            conversation_states.c.user_id == user_id,
            conversation_states.c.active_thread_id.in_(thread_ids),
        )
        .values(active_thread_id=None, version=conversation_states.c.version + 1)
    )
    connection.execute(
        thread_operation_applications.delete().where(
            thread_operation_applications.c.user_id == user_id,
            thread_operation_applications.c.thread_id.in_(thread_ids),
        )
    )
    connection.execute(
        conversation_threads.delete().where(
            conversation_threads.c.user_id == user_id,
            conversation_threads.c.id.in_(thread_ids),
        )
    )
    return len(thread_ids)


def prune_threads_from_missing_chats(user_id: str) -> int:
    """Delete threads left behind by chats deleted before deletes cleaned threads."""
    owner_id = _require_user_id(user_id, "conversation thread prune")
    with ENGINE.begin() as connection:
        existing = set(
            connection.execute(
                select(agent_conversations.c.id).where(agent_conversations.c.user_id == owner_id)
            ).scalars().all()
        )
        referenced = {
            conversation_id
            for row in connection.execute(
                select(
                    conversation_threads.c.created_in_conversation_id,
                    conversation_threads.c.last_conversation_id,
                ).where(conversation_threads.c.user_id == owner_id)
            ).all()
            for conversation_id in row
        }
        return _delete_threads_only_from(connection, owner_id, referenced - existing)


def _only_from(user_id: str, conversation_ids: set[str]):
    return (
        (conversation_threads.c.user_id == user_id)
        & conversation_threads.c.created_in_conversation_id.in_(conversation_ids)
        & conversation_threads.c.last_conversation_id.in_(conversation_ids)
    )


def _get_conversation_state(conversation_id: str, user_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(conversation_states).where(
                conversation_states.c.conversation_id == conversation_id,
                conversation_states.c.user_id == user_id,
            )
        ).mappings().first()
    return _state_from_row(row) if row else None


def _save_conversation_state(
    payload: dict[str, Any],
    *,
    expected_version: int,
) -> dict[str, Any]:
    conversation_id = str(payload["conversation_id"])
    owner_id = str(payload["user_id"])
    with ENGINE.begin() as connection:
        _require_owned_conversation(connection, conversation_id, owner_id)
        _require_available_thread(
            connection,
            payload.get("active_thread_id"),
            owner_id,
        )
        current = connection.execute(
            select(conversation_states).where(
                conversation_states.c.conversation_id == conversation_id,
                conversation_states.c.user_id == owner_id,
            )
        ).mappings().first()
        values = {
            "state_through_message_index": payload["state_through_message_index"],
            "active_thread_id": payload.get("active_thread_id"),
            "user_need": payload["user_need"],
            "session_goal": _protect_optional_text(owner_id, payload.get("session_goal")),
        }
        if current is None:
            if expected_version != 0:
                raise ConversationStateConflictError("new conversation state expects version 0")
            connection.execute(
                conversation_states.insert().values(
                    conversation_id=conversation_id,
                    user_id=owner_id,
                    version=1,
                    **values,
                )
            )
        else:
            if int(current["version"]) != expected_version:
                raise ConversationStateConflictError("conversation state version is stale")
            if payload["state_through_message_index"] < current["state_through_message_index"]:
                raise ConversationStateConflictError("conversation state cannot move backwards")
            result = connection.execute(
                conversation_states.update()
                .where(
                    conversation_states.c.conversation_id == conversation_id,
                    conversation_states.c.user_id == owner_id,
                    conversation_states.c.version == expected_version,
                )
                .values(**values, version=expected_version + 1, updated_at=func.now())
            )
            if result.rowcount != 1:
                raise ConversationStateConflictError("conversation state changed concurrently")
        row = connection.execute(
            select(conversation_states).where(
                conversation_states.c.conversation_id == conversation_id
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


def _require_available_thread(connection, thread_id: str | None, user_id: str) -> None:
    if not thread_id:
        return
    row = connection.execute(
        select(conversation_threads.c.status).where(
            conversation_threads.c.id == thread_id,
            conversation_threads.c.user_id == user_id,
        )
    ).first()
    if not row:
        raise ValueError("active conversation thread was not found for this user")
    if row[0] != "open":
        raise ValueError("only an open conversation thread can be active")


def _protected_thread_values(payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    values = dict(payload)
    for key in ("created_at", "updated_at"):
        if values.get(key) is None:
            values.pop(key, None)
    for key in ("title", "summary"):
        if key in values:
            values[key] = _protect_text(user_id, values[key])
    for key in ("next_angle", "closure_reason"):
        if key in values:
            values[key] = _protect_optional_text(user_id, values[key])
    return values


def _protect_optional_text(user_id: str, value: str | None) -> str | None:
    return _protect_text(user_id, value) if value is not None else None


def _thread_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "created_in_conversation_id": row["created_in_conversation_id"],
        "last_conversation_id": row["last_conversation_id"],
        "title": _unprotect_text(row["user_id"], row["title"]),
        "summary": _unprotect_text(row["user_id"], row["summary"]),
        "origin": row["origin"],
        "matching_dimension": row["matching_dimension"],
        "status": row["status"],
        "depth": row["depth"],
        "user_interest": row["user_interest"],
        "salience": row["salience"],
        "next_angle": _unprotect_optional_text(row["user_id"], row["next_angle"]),
        "first_message_index": row["first_message_index"],
        "last_message_index": row["last_message_index"],
        "closure_reason": _unprotect_optional_text(row["user_id"], row["closure_reason"]),
        "version": row["version"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def _state_from_row(row: Any) -> dict[str, Any]:
    return {
        "conversation_id": row["conversation_id"],
        "user_id": row["user_id"],
        "state_through_message_index": row["state_through_message_index"],
        "active_thread_id": row["active_thread_id"],
        "user_need": row["user_need"],
        "session_goal": _unprotect_optional_text(row["user_id"], row["session_goal"]),
        "version": row["version"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def _unprotect_optional_text(user_id: str, value: Any) -> str | None:
    return _unprotect_text(user_id, value) if value is not None else None


__all__ = ["prune_threads_from_missing_chats", "threads_only_from_conversation"]
