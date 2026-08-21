"""Atomically applies validated memory operations and records their audit trail."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from security.encryption import decrypt_json, maybe_encrypt_json

from .database import ENGINE
from .profile_facts import (
    _find_existing_profile_fact_row,
    _profile_fact_from_row,
    _profile_fact_payload,
    _upsert_profile_fact_in_transaction,
)
from .schema import agent_conversations, memory_operation_applications, profile_facts
from .utils import _isoformat_utc, _require_user_id

_APPLIED_OPERATIONS = {"add", "reinforce"}
_DEFERRED_OPERATIONS = {"supersede", "retract"}
_SUPPORTED_OPERATIONS = _APPLIED_OPERATIONS | _DEFERRED_OPERATIONS


def apply_memory_operation_batch(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply one validated batch exactly once or return its committed outcome."""
    user_id = _require_user_id(payload.get("user_id"), "memory operation batch")
    conversation_id = str(payload.get("conversation_id") or "").strip()
    batch_key = str(payload.get("batch_key") or "").strip()
    operations = payload.get("operations")
    if not conversation_id or not batch_key:
        raise ValueError("memory operation batch requires conversation_id and batch_key")
    if not isinstance(operations, list):
        raise ValueError("memory operation batch operations must be a list")
    _validate_operation_order(operations)

    with ENGINE.begin() as connection:
        _require_owned_conversation(connection, conversation_id, user_id)
        existing_rows = _batch_rows(connection, user_id, conversation_id, batch_key)
        if existing_rows:
            _validate_idempotent_retry(existing_rows, operations)
            return _batch_result(existing_rows, idempotent=True)

        stored_rows = []
        for operation in operations:
            stored_rows.append(
                _apply_operation(
                    connection,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    batch_key=batch_key,
                    operation=operation,
                )
            )
        return _batch_result(stored_rows, idempotent=False)


def list_memory_operation_applications(
    user_id: str,
    conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return a user's decrypted operation audit rows in deterministic order."""
    owner_id = _require_user_id(user_id, "memory operation application list")
    statement = select(memory_operation_applications).where(
        memory_operation_applications.c.user_id == owner_id
    )
    if conversation_id is not None:
        statement = statement.where(
            memory_operation_applications.c.conversation_id == conversation_id
        )
    statement = statement.order_by(
        memory_operation_applications.c.created_at.asc(),
        memory_operation_applications.c.operation_index.asc(),
    )
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_application_from_row(row) for row in rows]


def _apply_operation(
    connection,
    *,
    user_id: str,
    conversation_id: str,
    batch_key: str,
    operation: dict[str, Any],
):
    operation_kind = str(operation.get("operation") or "")
    if operation_kind not in _SUPPORTED_OPERATIONS:
        raise ValueError(f"unsupported memory operation: {operation_kind or 'missing'}")

    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    target_memory_id = operation.get("target_memory_id")
    result_memory_id: str | None = None
    if operation_kind == "add":
        fact_payload = _add_fact_payload(user_id, conversation_id, operation)
        normalized_payload = _profile_fact_payload(fact_payload)
        existing = _find_existing_profile_fact_row(connection, normalized_payload)
        before = _profile_fact_from_row(existing) if existing else None
        after = _upsert_profile_fact_in_transaction(connection, fact_payload)
        result_memory_id = str(after["id"])
        outcome = "applied"
    else:
        target = _active_target(connection, user_id, target_memory_id)
        before = _profile_fact_from_row(target)
        if operation_kind == "reinforce":
            reinforcement = {
                **before,
                "confidence": max(
                    float(before.get("confidence") or 0),
                    float(operation.get("confidence") or 0),
                ),
                "source_kind": "memory_background_v2",
                "source_id": conversation_id,
                "evidence": list(before.get("evidence") or [])
                + list(operation.get("evidence") or []),
            }
            after = _upsert_profile_fact_in_transaction(connection, reinforcement)
            result_memory_id = str(after["id"])
            outcome = "applied"
        else:
            after = before
            result_memory_id = str(before["id"])
            outcome = "deferred"

    row_id = str(uuid4())
    connection.execute(
        memory_operation_applications.insert().values(
            id=row_id,
            user_id=user_id,
            conversation_id=conversation_id,
            batch_key=batch_key,
            operation_index=int(operation["operation_index"]),
            operation_fingerprint=str(operation["operation_fingerprint"]),
            operation_kind=operation_kind,
            outcome=outcome,
            target_memory_id=target_memory_id,
            result_memory_id=result_memory_id,
            operation_json=maybe_encrypt_json(user_id, operation),
            before_json=maybe_encrypt_json(user_id, before) if before is not None else None,
            after_json=maybe_encrypt_json(user_id, after) if after is not None else None,
        )
    )
    return connection.execute(
        select(memory_operation_applications).where(
            memory_operation_applications.c.id == row_id
        )
    ).mappings().one()


def _add_fact_payload(
    user_id: str,
    conversation_id: str,
    operation: dict[str, Any],
) -> dict[str, Any]:
    for name in ("data_point_type", "category", "key", "label"):
        if not str(operation.get(name) or "").strip():
            raise ValueError(f"add operation requires {name}")
    if operation.get("value") is None:
        raise ValueError("add operation requires value")
    data_point_type = str(operation["data_point_type"])
    stored_fact_type = (
        data_point_type
        if data_point_type in {"profile_fact", "matching_fact"}
        else "chat_context_fact"
    )
    used_for_matching = data_point_type in {"profile_fact", "matching_fact"}
    value = operation["value"]
    if isinstance(value, dict):
        stored_value = {**value, "_data_point_type": data_point_type}
    else:
        stored_value = {"detail": value, "_data_point_type": data_point_type}
    return {
        "user_id": user_id,
        "category": operation["category"],
        "key": operation["key"],
        "label": operation["label"],
        "value": stored_value,
        "confidence": operation.get("confidence", 0.5),
        "fact_type": stored_fact_type,
        "confidence_state": "active" if used_for_matching else "candidate",
        "source_kind": "memory_background_v2",
        "source_id": conversation_id,
        "evidence": operation.get("evidence") or [],
        "status": "active",
        "visibility": "internal",
        "used_for_matching": used_for_matching,
        "used_for_chat_context": True,
    }


def _active_target(connection, user_id: str, target_memory_id: Any):
    if not isinstance(target_memory_id, str) or not target_memory_id:
        raise ValueError("operation requires an active memory target owned by the user")
    row = connection.execute(
        select(profile_facts).where(
            profile_facts.c.id == target_memory_id,
            profile_facts.c.user_id == user_id,
            profile_facts.c.status == "active",
        )
    ).mappings().first()
    if not row:
        raise ValueError("operation requires an active memory target owned by the user")
    return row


def _validate_operation_order(operations: list[dict[str, Any]]) -> None:
    for expected_index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ValueError("memory operation must be an object")
        if operation.get("operation_index") != expected_index:
            raise ValueError("memory operation indexes must be contiguous and ordered")
        if not str(operation.get("operation_fingerprint") or "").strip():
            raise ValueError("memory operation requires operation_fingerprint")


def _validate_idempotent_retry(existing_rows, operations: list[dict[str, Any]]) -> None:
    if len(existing_rows) != len(operations):
        raise ValueError("memory batch retry does not match its committed operation count")
    for row, operation in zip(existing_rows, operations, strict=True):
        if (
            int(row["operation_index"]) != int(operation["operation_index"])
            or row["operation_fingerprint"] != operation["operation_fingerprint"]
        ):
            raise ValueError("memory batch retry does not match its committed operations")


def _batch_rows(connection, user_id: str, conversation_id: str, batch_key: str):
    return connection.execute(
        select(memory_operation_applications)
        .where(
            memory_operation_applications.c.user_id == user_id,
            memory_operation_applications.c.conversation_id == conversation_id,
            memory_operation_applications.c.batch_key == batch_key,
        )
        .order_by(memory_operation_applications.c.operation_index.asc())
    ).mappings().all()


def _batch_result(rows, *, idempotent: bool) -> dict[str, Any]:
    applications = [_application_from_row(row) for row in rows]
    return {
        "batch_key": applications[0]["batch_key"] if applications else None,
        "idempotent": idempotent,
        "applied_count": sum(row["outcome"] == "applied" for row in applications),
        "deferred_count": sum(row["outcome"] == "deferred" for row in applications),
        "operations": applications,
    }


def _application_from_row(row) -> dict[str, Any]:
    user_id = row["user_id"]
    return {
        "id": row["id"],
        "user_id": user_id,
        "conversation_id": row["conversation_id"],
        "batch_key": row["batch_key"],
        "operation_index": row["operation_index"],
        "operation_fingerprint": row["operation_fingerprint"],
        "operation_kind": row["operation_kind"],
        "outcome": row["outcome"],
        "target_memory_id": row["target_memory_id"],
        "result_memory_id": row["result_memory_id"],
        "operation": decrypt_json(user_id, row["operation_json"]),
        "before": decrypt_json(user_id, row["before_json"]),
        "after": decrypt_json(user_id, row["after_json"]),
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _require_owned_conversation(connection, conversation_id: str, user_id: str) -> None:
    found = connection.execute(
        select(agent_conversations.c.id).where(
            agent_conversations.c.id == conversation_id,
            agent_conversations.c.user_id == user_id,
        )
    ).first()
    if not found:
        raise ValueError("conversation was not found for this user")


__all__ = [
    "apply_memory_operation_batch",
    "list_memory_operation_applications",
]
