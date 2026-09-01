"""Persists encrypted v3 memories and their normalized evidence records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

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
from .schema import agent_conversations, agent_memories, agent_memory_evidence
from .utils import _isoformat_utc, _protect_text, _require_user_id, _unprotect_text


def create_agent_memory(payload: dict[str, Any]) -> dict[str, Any]:
    """Create one validated memory; storage owns its ID and audit timestamps."""
    record = _record_from_create_payload(payload)
    with ENGINE.begin() as connection:
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
        row = connection.execute(
            select(agent_memories).where(agent_memories.c.id == record.id)
        ).mappings().one()
        return _memory_from_row(connection, row)


def get_agent_memory(memory_id: str, user_id: str) -> dict[str, Any] | None:
    owner_id = _require_user_id(user_id, "agent memory")
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(agent_memories).where(
                agent_memories.c.id == memory_id,
                agent_memories.c.user_id == owner_id,
            )
        ).mappings().first()
        return _memory_from_row(connection, row) if row else None


def list_agent_memories(user_id: str) -> list[dict[str, Any]]:
    """List owned v3 memories for storage verification; ranking comes later."""
    owner_id = _require_user_id(user_id, "agent memory")
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(agent_memories)
            .where(agent_memories.c.user_id == owner_id)
            .order_by(agent_memories.c.updated_at.desc(), agent_memories.c.id.asc())
        ).mappings().all()
        return [_memory_from_row(connection, row) for row in rows]


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
        last_reinforced_at=_datetime(
            payload.get("last_reinforced_at"), "last_reinforced_at"
        ),
        supersedes_memory_id=_optional_text(payload.get("supersedes_memory_id")),
        extractor=_optional_text(payload.get("extractor")),
        extractor_model=_optional_text(payload.get("extractor_model")),
        schema_version=int(payload.get("schema_version", MEMORY_SCHEMA_VERSION)),
    )


def _memory_from_row(connection, row) -> dict[str, Any]:
    evidence_rows = connection.execute(
        select(agent_memory_evidence)
        .where(
            agent_memory_evidence.c.memory_id == row["id"],
            agent_memory_evidence.c.user_id == row["user_id"],
        )
        .order_by(agent_memory_evidence.c.observed_at.asc(), agent_memory_evidence.c.id.asc())
    ).mappings().all()
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


__all__ = ["create_agent_memory", "get_agent_memory", "list_agent_memories"]
