"""Atomically applies one validated thread operation exactly once per batch."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from security.encryption import decrypt_json, maybe_encrypt_json

from .conversation_threads import (
    ConversationStateConflictError,
    _protected_thread_values,
    _require_owned_conversation,
    _thread_from_row,
)
from .database import ENGINE
from .schema import (
    conversation_states,
    conversation_threads,
    thread_operation_applications,
)
from .utils import _isoformat_utc, _require_user_id


_UPDATE_OPERATIONS = {"continue", "switch", "pause", "complete", "block"}
_MUTABLE_THREAD_FIELDS = {
    "last_conversation_id",
    "title",
    "summary",
    "matching_dimension",
    "status",
    "depth",
    "user_interest",
    "salience",
    "next_angle",
    "last_message_index",
    "closure_reason",
}


def apply_thread_operation_once(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a normalized operation and its audit row in one transaction."""
    user_id = _require_user_id(payload.get("user_id"), "thread operation application")
    conversation_id = str(payload.get("conversation_id") or "").strip()
    batch_key = str(payload.get("batch_key") or "").strip()
    fingerprint = str(payload.get("operation_fingerprint") or "").strip()
    operation = payload.get("operation")
    if not conversation_id or not batch_key or not fingerprint:
        raise ValueError(
            "thread operation application requires conversation_id, batch_key, and fingerprint"
        )
    if not isinstance(operation, dict):
        raise ValueError("thread operation must be an object")
    operation_kind = str(operation.get("operation") or "")
    if operation_kind not in {"create", *_UPDATE_OPERATIONS}:
        raise ValueError(f"unsupported thread operation: {operation_kind or 'missing'}")

    with ENGINE.begin() as connection:
        _require_owned_conversation(connection, conversation_id, user_id)
        existing = connection.execute(
            select(thread_operation_applications).where(
                thread_operation_applications.c.user_id == user_id,
                thread_operation_applications.c.conversation_id == conversation_id,
                thread_operation_applications.c.batch_key == batch_key,
            )
        ).mappings().first()
        if existing:
            if existing["operation_fingerprint"] != fingerprint:
                raise ValueError(
                    "thread batch retry does not match its committed operation"
                )
            return _application_from_row(existing, idempotent=True)

        result = (
            _create_thread(connection, user_id, conversation_id, operation)
            if operation_kind == "create"
            else _update_thread(connection, user_id, operation)
        )
        row_id = str(uuid4())
        connection.execute(
            thread_operation_applications.insert().values(
                id=row_id,
                user_id=user_id,
                conversation_id=conversation_id,
                batch_key=batch_key,
                operation_fingerprint=fingerprint,
                operation_kind=operation_kind,
                thread_id=result["id"],
                operation_json=maybe_encrypt_json(user_id, operation),
                result_json=maybe_encrypt_json(user_id, result),
            )
        )
        stored = connection.execute(
            select(thread_operation_applications).where(
                thread_operation_applications.c.id == row_id
            )
        ).mappings().one()
    return _application_from_row(stored, idempotent=False)


def list_thread_operation_applications(
    user_id: str,
    conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return decrypted thread-application audit rows for one user."""
    owner_id = _require_user_id(user_id, "thread operation application list")
    statement = select(thread_operation_applications).where(
        thread_operation_applications.c.user_id == owner_id
    )
    if conversation_id is not None:
        statement = statement.where(
            thread_operation_applications.c.conversation_id == conversation_id
        )
    statement = statement.order_by(thread_operation_applications.c.created_at.asc())
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_application_from_row(row, idempotent=False) for row in rows]


def _create_thread(connection, user_id: str, conversation_id: str, operation: dict[str, Any]):
    thread = operation.get("thread")
    if not isinstance(thread, dict):
        raise ValueError("create operation requires a normalized thread")
    if thread.get("user_id") != user_id:
        raise ValueError("created thread must belong to the application user")
    if (
        thread.get("created_in_conversation_id") != conversation_id
        or thread.get("last_conversation_id") != conversation_id
    ):
        raise ValueError("created thread must reference the application conversation")
    connection.execute(
        conversation_threads.insert().values(**_protected_thread_values(thread, user_id))
    )
    row = connection.execute(
        select(conversation_threads).where(conversation_threads.c.id == thread["id"])
    ).mappings().one()
    return _thread_from_row(row)


def _update_thread(connection, user_id: str, operation: dict[str, Any]):
    thread_id = operation.get("thread_id")
    changes = operation.get("changes")
    if not isinstance(thread_id, str) or not isinstance(changes, dict):
        raise ValueError("existing thread operation requires thread_id and changes")
    unknown = set(changes) - _MUTABLE_THREAD_FIELDS
    if unknown:
        raise ValueError(f"thread fields cannot be changed: {', '.join(sorted(unknown))}")
    current = connection.execute(
        select(conversation_threads).where(
            conversation_threads.c.id == thread_id,
            conversation_threads.c.user_id == user_id,
        )
    ).mappings().first()
    if not current:
        raise ValueError("conversation thread was not found for this user")
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

    expected_version = int(current["version"])
    values = _protected_thread_values(changes, user_id)
    values.update(version=expected_version + 1, updated_at=func.now())
    updated = connection.execute(
        conversation_threads.update()
        .where(
            conversation_threads.c.id == thread_id,
            conversation_threads.c.user_id == user_id,
            conversation_threads.c.version == expected_version,
        )
        .values(**values)
    )
    if updated.rowcount != 1:
        raise ConversationStateConflictError("conversation thread changed concurrently")
    row = connection.execute(
        select(conversation_threads).where(conversation_threads.c.id == thread_id)
    ).mappings().one()
    return _thread_from_row(row)


def _application_from_row(row, *, idempotent: bool) -> dict[str, Any]:
    user_id = row["user_id"]
    return {
        "id": row["id"],
        "user_id": user_id,
        "conversation_id": row["conversation_id"],
        "batch_key": row["batch_key"],
        "operation_fingerprint": row["operation_fingerprint"],
        "operation_kind": row["operation_kind"],
        "thread_id": row["thread_id"],
        "operation": decrypt_json(user_id, row["operation_json"]),
        "result": decrypt_json(user_id, row["result_json"]),
        "idempotent": idempotent,
        "created_at": _isoformat_utc(row["created_at"]),
    }


__all__ = ["apply_thread_operation_once", "list_thread_operation_applications"]
