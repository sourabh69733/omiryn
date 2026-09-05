"""Persists encrypted v3 memories and their normalized evidence records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select

from agent.memory_engine.memories import (
    MEMORY_SCHEMA_VERSION,
    MemoryEvidence,
    MemoryKind,
    MemoryPurpose,
    MemoryRecord,
    MemorySensitivity,
    MemoryStatus,
    MemoryUse,
)
from security.encryption import decrypt_json, maybe_encrypt_json

from .database import ENGINE
from .schema import (
    agent_conversations,
    agent_memories,
    agent_memory_evidence,
    memory_operation_applications,
)
from .utils import _isoformat_utc, _protect_text, _require_user_id, _unprotect_text


def create_agent_memory(payload: dict[str, Any]) -> dict[str, Any]:
    """Create one validated memory; storage owns its ID and audit timestamps."""
    with ENGINE.begin() as connection:
        return _create_agent_memory(connection, payload)


def _create_agent_memory(connection, payload: dict[str, Any]) -> dict[str, Any]:
    record = _record_from_create_payload(payload)
    _require_owned_evidence_conversations(connection, record)
    if record.supersedes_memory_id:
        _require_owned_memory(connection, record.supersedes_memory_id, record.user_id)

    connection.execute(
        agent_memories.insert().values(
            id=record.id,
            user_id=record.user_id,
            kind=record.kind.value,
            purposes_json=sorted(purpose.value for purpose in record.purposes),
            key=record.key,
            value_json=maybe_encrypt_json(record.user_id, record.value),
            allowed_uses_json=sorted(use.value for use in record.allowed_uses),
            status=record.status.value,
            sensitivity=record.sensitivity.value,
            confidence=record.confidence,
            importance=record.importance,
            occurred_at=record.occurred_at,
            valid_from=record.valid_from,
            valid_until=record.valid_until,
            last_reinforced_at=record.last_reinforced_at,
            supersedes_memory_id=record.supersedes_memory_id,
            extractor=record.extractor,
            extractor_model=record.extractor_model,
            schema_version=record.schema_version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
    )
    for evidence in record.evidence:
        connection.execute(
            agent_memory_evidence.insert().values(
                id=str(uuid4()),
                memory_id=record.id,
                user_id=record.user_id,
                conversation_id=evidence.conversation_id,
                message_id=evidence.message_id,
                message_index=evidence.message_index,
                exact_quote=_protect_text(record.user_id, evidence.exact_quote),
                observed_at=evidence.observed_at,
            )
        )
    row = (
        connection.execute(select(agent_memories).where(agent_memories.c.id == record.id))
        .mappings()
        .one()
    )
    return _memory_from_row(connection, row)


def get_agent_memory(memory_id: str, user_id: str) -> dict[str, Any] | None:
    owner_id = _require_user_id(user_id, "agent memory")
    with ENGINE.begin() as connection:
        row = (
            connection.execute(
                select(agent_memories).where(
                    agent_memories.c.id == memory_id,
                    agent_memories.c.user_id == owner_id,
                )
            )
            .mappings()
            .first()
        )
        return _memory_from_row(connection, row) if row else None


def list_agent_memories(user_id: str) -> list[dict[str, Any]]:
    """List owned v3 memories for storage verification; ranking comes later."""
    owner_id = _require_user_id(user_id, "agent memory")
    with ENGINE.begin() as connection:
        rows = (
            connection.execute(
                select(agent_memories)
                .where(agent_memories.c.user_id == owner_id)
                .order_by(agent_memories.c.updated_at.desc(), agent_memories.c.id.asc())
            )
            .mappings()
            .all()
        )
        return [_memory_from_row(connection, row) for row in rows]


def delete_agent_memory(memory_id: str, user_id: str) -> bool:
    """Permanently delete one owned memory and its private supporting records."""
    owner_id = _require_user_id(user_id, "agent memory")
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(agent_memories.c.id).where(
                agent_memories.c.id == memory_id,
                agent_memories.c.user_id == owner_id,
            )
        ).first()
        if not existing:
            return False
        connection.execute(
            agent_memory_evidence.delete().where(
                agent_memory_evidence.c.memory_id == memory_id,
                agent_memory_evidence.c.user_id == owner_id,
            )
        )
        connection.execute(
            memory_operation_applications.delete().where(
                memory_operation_applications.c.user_id == owner_id,
                or_(
                    memory_operation_applications.c.target_memory_id == memory_id,
                    memory_operation_applications.c.result_memory_id == memory_id,
                ),
            )
        )
        connection.execute(
            agent_memories.update()
            .where(
                agent_memories.c.user_id == owner_id,
                agent_memories.c.supersedes_memory_id == memory_id,
            )
            .values(supersedes_memory_id=None, updated_at=func.now())
        )
        result = connection.execute(
            agent_memories.delete().where(
                agent_memories.c.id == memory_id,
                agent_memories.c.user_id == owner_id,
            )
        )
    return bool(result.rowcount)


def apply_agent_memory_operation_batch(payload: dict[str, Any]) -> dict[str, Any]:
    """Atomically and idempotently apply one validated v3 lifecycle batch."""
    user_id = _require_user_id(str(payload.get("user_id") or ""), "memory batch")
    conversation_id = str(payload.get("conversation_id") or "").strip()
    batch_key = str(payload.get("batch_key") or "").strip()
    operations = payload.get("operations")
    if not conversation_id or not batch_key:
        raise ValueError("memory batch requires conversation_id and batch_key")
    if not isinstance(operations, list):
        raise ValueError("memory batch operations must be an array")
    _validate_batch_operations(operations)

    with ENGINE.begin() as connection:
        _require_owned_conversation(connection, conversation_id, user_id)
        existing = _application_rows(connection, user_id, conversation_id, batch_key)
        if existing:
            _validate_idempotent_retry(existing, operations)
            return _batch_result(connection, existing, idempotent=True)

        targeted: set[str] = set()
        for operation in operations:
            target_id = _optional_text(operation.get("target_memory_id"))
            if target_id and target_id in targeted:
                raise ValueError("a memory can be targeted only once per batch")
            if target_id:
                targeted.add(target_id)
            operation_kind, outcome, before, after = _apply_lifecycle_operation(
                connection,
                user_id,
                operation,
            )
            connection.execute(
                memory_operation_applications.insert().values(
                    id=str(uuid4()),
                    user_id=user_id,
                    conversation_id=conversation_id,
                    batch_key=batch_key,
                    operation_index=operation["operation_index"],
                    operation_fingerprint=operation["operation_fingerprint"],
                    operation_kind=operation_kind,
                    outcome=outcome,
                    target_memory_id=target_id,
                    result_memory_id=after["id"] if after else None,
                    operation_json=maybe_encrypt_json(user_id, operation),
                    before_json=(maybe_encrypt_json(user_id, before) if before else None),
                    after_json=(maybe_encrypt_json(user_id, after) if after else None),
                )
            )
        rows = _application_rows(connection, user_id, conversation_id, batch_key)
        return _batch_result(connection, rows, idempotent=False)


def apply_agent_memory_add_batch(payload: dict[str, Any]) -> dict[str, Any]:
    """Compatibility alias for callers that still submit add-only v3 batches."""
    return apply_agent_memory_operation_batch(payload)


def _validate_batch_operations(operations: list[dict[str, Any]]) -> None:
    supported = {"add", "reinforce", "supersede", "retract"}
    for expected_index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ValueError("memory operation must be an object")
        if operation.get("operation_index") != expected_index:
            raise ValueError("memory operation indexes must be contiguous and ordered")
        if not str(operation.get("operation_fingerprint") or "").strip():
            raise ValueError("memory operation requires operation_fingerprint")
        if operation.get("operation") not in supported:
            raise ValueError("memory operation kind is unsupported")


def _apply_lifecycle_operation(connection, user_id: str, operation: dict[str, Any]):
    name = operation["operation"]
    if name == "add":
        return _apply_add_operation(connection, user_id, operation)
    target_id = str(operation.get("target_memory_id") or "").strip()
    row = _owned_active_memory_row(connection, target_id, user_id)
    before = _memory_from_row(connection, row)
    if name == "reinforce":
        after = _reinforce_memory(
            connection,
            row,
            operation.get("evidence"),
            confidence=float(operation.get("confidence", 0.0)),
            importance=float(operation.get("importance", 0.0)),
        )
        return "reinforce_v3", "applied", before, after
    if name == "supersede":
        memory = operation.get("memory")
        if not isinstance(memory, dict):
            raise ValueError("memory supersede operation requires a replacement memory")
        if memory.get("supersedes_memory_id") != target_id:
            raise ValueError("replacement must reference its superseded memory")
        _reject_active_key_conflict(
            connection,
            user_id,
            memory,
            excluded_memory_id=target_id,
        )
        replacement = _create_agent_memory(
            connection,
            {**memory, "user_id": user_id},
        )
        now = datetime.now(UTC)
        connection.execute(
            agent_memories.update()
            .where(agent_memories.c.id == target_id, agent_memories.c.user_id == user_id)
            .values(status=MemoryStatus.SUPERSEDED.value, updated_at=now)
        )
        return "supersede_v3", "applied", before, replacement
    if name == "retract":
        _validate_operation_evidence(connection, user_id, operation.get("evidence"))
        now = datetime.now(UTC)
        connection.execute(
            agent_memories.update()
            .where(agent_memories.c.id == target_id, agent_memories.c.user_id == user_id)
            .values(status=MemoryStatus.RETRACTED.value, updated_at=now)
        )
        updated = _memory_by_id(connection, target_id)
        return "retract_v3", "applied", before, updated
    raise ValueError("memory operation kind is unsupported")


def _apply_add_operation(connection, user_id: str, operation: dict[str, Any]):
    memory = operation.get("memory")
    if not isinstance(memory, dict):
        raise ValueError("memory add operation requires a memory object")
    conflict = _active_key_conflict(connection, user_id, memory)
    if conflict is not None:
        before = _memory_from_row(connection, conflict)
        if not _same_memory_content(conflict, memory):
            raise ValueError("active memory with this kind and key requires supersede")
        after = _reinforce_memory(
            connection,
            conflict,
            memory.get("evidence"),
            confidence=float(memory.get("confidence", 0.0)),
            importance=float(memory.get("importance", 0.0)),
        )
        return "reinforce_duplicate_v3", "deduplicated", before, after
    saved = _create_agent_memory(connection, {**memory, "user_id": user_id})
    return "add_v3", "applied", None, saved


def _reinforce_memory(
    connection,
    row,
    evidence: Any,
    *,
    confidence: float,
    importance: float,
) -> dict[str, Any]:
    _append_memory_evidence(connection, row["id"], row["user_id"], evidence)
    now = datetime.now(UTC)
    connection.execute(
        agent_memories.update()
        .where(agent_memories.c.id == row["id"], agent_memories.c.user_id == row["user_id"])
        .values(
            confidence=max(float(row["confidence"]), confidence),
            importance=max(float(row["importance"]), importance),
            last_reinforced_at=now,
            updated_at=now,
        )
    )
    return _memory_by_id(connection, row["id"])


def _append_memory_evidence(
    connection,
    memory_id: str,
    user_id: str,
    value: Any,
) -> None:
    evidence_items = _validated_operation_evidence(connection, user_id, value)
    existing = (
        connection.execute(
            select(agent_memory_evidence).where(
                agent_memory_evidence.c.memory_id == memory_id,
                agent_memory_evidence.c.user_id == user_id,
            )
        )
        .mappings()
        .all()
    )
    pointers = {
        (row["conversation_id"], row["message_id"], row["message_index"]) for row in existing
    }
    for evidence in evidence_items:
        pointer = (
            evidence["conversation_id"],
            evidence["message_id"],
            evidence["message_index"],
        )
        if pointer in pointers:
            continue
        connection.execute(
            agent_memory_evidence.insert().values(
                id=str(uuid4()),
                memory_id=memory_id,
                user_id=user_id,
                conversation_id=evidence["conversation_id"],
                message_id=evidence["message_id"],
                message_index=evidence["message_index"],
                exact_quote=_protect_text(user_id, evidence["exact_quote"]),
                observed_at=evidence["observed_at"],
            )
        )
        pointers.add(pointer)


def _validate_operation_evidence(connection, user_id: str, value: Any) -> None:
    _validated_operation_evidence(connection, user_id, value)


def _validated_operation_evidence(connection, user_id: str, value: Any):
    items = _evidence_items(value)
    normalized = []
    for item in items:
        conversation_id = str(item.get("conversation_id") or "").strip()
        message_id = _optional_text(item.get("message_id"))
        message_index = item.get("message_index")
        exact_quote = str(item.get("exact_quote") or "").strip()
        observed_at = _datetime(item.get("observed_at"), "observed_at", required=True)
        if not conversation_id or not exact_quote:
            raise ValueError("memory operation evidence is incomplete")
        if message_id is None and (
            not isinstance(message_index, int) or isinstance(message_index, bool)
        ):
            raise ValueError("memory operation evidence requires a message pointer")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("memory operation evidence time must be timezone-aware")
        normalized.append(
            {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "message_index": message_index,
                "exact_quote": exact_quote,
                "observed_at": observed_at,
            }
        )
    conversation_ids = {item["conversation_id"] for item in normalized}
    rows = connection.execute(
        select(agent_conversations.c.id).where(
            agent_conversations.c.user_id == user_id,
            agent_conversations.c.id.in_(conversation_ids),
        )
    ).all()
    if {row[0] for row in rows} != conversation_ids:
        raise ValueError("memory evidence conversation was not found for this user")
    return normalized


def _owned_active_memory_row(connection, memory_id: str, user_id: str):
    row = (
        connection.execute(
            select(agent_memories).where(
                agent_memories.c.id == memory_id,
                agent_memories.c.user_id == user_id,
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ValueError("target memory was not found for this user")
    if row["status"] != MemoryStatus.ACTIVE.value:
        raise ValueError("target memory must be active")
    return row


def _memory_by_id(connection, memory_id: str) -> dict[str, Any]:
    row = (
        connection.execute(select(agent_memories).where(agent_memories.c.id == memory_id))
        .mappings()
        .one()
    )
    return _memory_from_row(connection, row)


def _active_key_conflict(connection, user_id: str, memory: dict[str, Any]):
    rows = (
        connection.execute(
            select(agent_memories).where(
                agent_memories.c.user_id == user_id,
                agent_memories.c.status == MemoryStatus.ACTIVE.value,
                agent_memories.c.kind == str(memory.get("kind") or ""),
            )
        )
        .mappings()
        .all()
    )
    key = str(memory.get("key") or "").strip().casefold()
    return next((row for row in rows if str(row["key"]).strip().casefold() == key), None)


def _reject_active_key_conflict(
    connection,
    user_id: str,
    memory: dict[str, Any],
    *,
    excluded_memory_id: str,
) -> None:
    conflict = _active_key_conflict(connection, user_id, memory)
    if conflict is not None and conflict["id"] != excluded_memory_id:
        raise ValueError("replacement conflicts with another active memory")


def _same_memory_content(row, memory: dict[str, Any]) -> bool:
    return (
        row["kind"] == memory.get("kind")
        and str(row["key"]).strip().casefold() == str(memory.get("key") or "").strip().casefold()
        and set(row["purposes_json"] or []) == set(memory.get("purposes") or [])
        and decrypt_json(row["user_id"], row["value_json"]) == memory.get("value")
    )


def _validate_idempotent_retry(rows, operations: list[dict[str, Any]]) -> None:
    if len(rows) != len(operations):
        raise ValueError("memory batch retry does not match its committed operation count")
    for row, operation in zip(rows, operations, strict=True):
        if (
            int(row["operation_index"]) != int(operation["operation_index"])
            or row["operation_fingerprint"] != operation["operation_fingerprint"]
        ):
            raise ValueError("memory batch retry does not match its committed operations")


def _application_rows(connection, user_id: str, conversation_id: str, batch_key: str):
    return (
        connection.execute(
            select(memory_operation_applications)
            .where(
                memory_operation_applications.c.user_id == user_id,
                memory_operation_applications.c.conversation_id == conversation_id,
                memory_operation_applications.c.batch_key == batch_key,
            )
            .order_by(memory_operation_applications.c.operation_index.asc())
        )
        .mappings()
        .all()
    )


def _batch_result(connection, rows, *, idempotent: bool) -> dict[str, Any]:
    memory_ids = [row["result_memory_id"] for row in rows if row["result_memory_id"]]
    memories = []
    for memory_id in memory_ids:
        row = (
            connection.execute(select(agent_memories).where(agent_memories.c.id == memory_id))
            .mappings()
            .one()
        )
        memories.append(_memory_from_row(connection, row))
    return {
        "batch_key": rows[0]["batch_key"] if rows else None,
        "idempotent": idempotent,
        "applied_count": len(memories),
        "deferred_count": 0,
        "memories": memories,
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


def _record_from_create_payload(payload: dict[str, Any]) -> MemoryRecord:
    now = datetime.now(UTC)
    user_id = _require_user_id(str(payload.get("user_id") or ""), "agent memory")
    evidence = tuple(
        MemoryEvidence(
            conversation_id=str(item.get("conversation_id") or ""),
            message_id=_optional_text(item.get("message_id")),
            message_index=item.get("message_index"),
            exact_quote=str(item.get("exact_quote") or ""),
            observed_at=_datetime(item.get("observed_at"), "observed_at", required=True),
        )
        for item in _evidence_items(payload.get("evidence"))
    )
    return MemoryRecord(
        id=str(uuid4()),
        user_id=user_id,
        kind=MemoryKind(str(payload.get("kind") or "")),
        purposes=frozenset(MemoryPurpose(str(value)) for value in payload.get("purposes") or ()),
        key=str(payload.get("key") or ""),
        value=payload.get("value"),
        evidence=evidence,
        created_at=now,
        updated_at=now,
        allowed_uses=frozenset(
            MemoryUse(str(value))
            for value in payload.get("allowed_uses") or (MemoryUse.REPLY_CONTEXT.value,)
        ),
        status=MemoryStatus(str(payload.get("status") or MemoryStatus.ACTIVE.value)),
        sensitivity=MemorySensitivity(
            str(payload.get("sensitivity") or MemorySensitivity.STANDARD.value)
        ),
        confidence=float(payload.get("confidence", 0.5)),
        importance=float(payload.get("importance", 0.5)),
        occurred_at=_datetime(payload.get("occurred_at"), "occurred_at"),
        valid_from=_datetime(payload.get("valid_from"), "valid_from"),
        valid_until=_datetime(payload.get("valid_until"), "valid_until"),
        last_reinforced_at=_datetime(payload.get("last_reinforced_at"), "last_reinforced_at"),
        supersedes_memory_id=_optional_text(payload.get("supersedes_memory_id")),
        extractor=_optional_text(payload.get("extractor")),
        extractor_model=_optional_text(payload.get("extractor_model")),
        schema_version=int(payload.get("schema_version", MEMORY_SCHEMA_VERSION)),
    )


def _memory_from_row(connection, row) -> dict[str, Any]:
    evidence_rows = (
        connection.execute(
            select(agent_memory_evidence)
            .where(
                agent_memory_evidence.c.memory_id == row["id"],
                agent_memory_evidence.c.user_id == row["user_id"],
            )
            .order_by(agent_memory_evidence.c.observed_at.asc(), agent_memory_evidence.c.id.asc())
        )
        .mappings()
        .all()
    )
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "kind": row["kind"],
        "purposes": list(row["purposes_json"] or []),
        "key": row["key"],
        "value": decrypt_json(row["user_id"], row["value_json"]),
        "allowed_uses": list(row["allowed_uses_json"] or []),
        "status": row["status"],
        "sensitivity": row["sensitivity"],
        "confidence": row["confidence"],
        "importance": row["importance"],
        "occurred_at": _isoformat_utc(row["occurred_at"]),
        "valid_from": _isoformat_utc(row["valid_from"]),
        "valid_until": _isoformat_utc(row["valid_until"]),
        "last_reinforced_at": _isoformat_utc(row["last_reinforced_at"]),
        "supersedes_memory_id": row["supersedes_memory_id"],
        "extractor": row["extractor"],
        "extractor_model": row["extractor_model"],
        "schema_version": row["schema_version"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
        "evidence": [
            {
                "id": evidence["id"],
                "conversation_id": evidence["conversation_id"],
                "message_id": evidence["message_id"],
                "message_index": evidence["message_index"],
                "exact_quote": _unprotect_text(row["user_id"], evidence["exact_quote"]),
                "observed_at": _isoformat_utc(evidence["observed_at"]),
            }
            for evidence in evidence_rows
        ],
    }


def _require_owned_evidence_conversations(connection, record: MemoryRecord) -> None:
    conversation_ids = {item.conversation_id for item in record.evidence}
    rows = connection.execute(
        select(agent_conversations.c.id).where(
            agent_conversations.c.user_id == record.user_id,
            agent_conversations.c.id.in_(conversation_ids),
        )
    ).all()
    if {row[0] for row in rows} != conversation_ids:
        raise ValueError("memory evidence conversation was not found for this user")


def _require_owned_memory(connection, memory_id: str, user_id: str) -> None:
    found = connection.execute(
        select(agent_memories.c.id).where(
            agent_memories.c.id == memory_id,
            agent_memories.c.user_id == user_id,
        )
    ).first()
    if not found:
        raise ValueError("superseded memory was not found for this user")


def _evidence_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("memory evidence must be a list of objects")
    return value


def _datetime(value: Any, name: str, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise ValueError(f"memory {name} is required")
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"memory {name} is invalid") from error
    if not isinstance(value, datetime):
        raise ValueError(f"memory {name} is invalid")
    return value


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = [
    "apply_agent_memory_add_batch",
    "apply_agent_memory_operation_batch",
    "create_agent_memory",
    "delete_agent_memory",
    "get_agent_memory",
    "list_agent_memories",
]
