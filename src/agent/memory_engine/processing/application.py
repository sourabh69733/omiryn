"""Maps validated model proposals to provider-neutral, auditable memory writes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from agent.config import agent_pipeline_config
from storage.memory_applications import apply_memory_operation_batch

from .models import MemoryBatch, MemoryOperation


@dataclass(frozen=True)
class MemoryApplicationResult:
    """Committed outcome for one validated background-memory batch."""

    batch_key: str
    idempotent: bool
    applied_count: int
    deferred_count: int
    operations: tuple[dict[str, Any], ...] = ()


def memory_background_v2_live_writes_enabled() -> bool:
    """Enable writes only in the centrally validated live rollout."""
    return agent_pipeline_config().live_memory_writes


def apply_validated_memory_analysis(
    batch: MemoryBatch,
    analysis: Any,
) -> MemoryApplicationResult:
    """Resolve trusted evidence and atomically persist a validated analysis."""
    if not getattr(analysis, "valid", False):
        raise ValueError("live writes require a validated memory analysis")
    operations = tuple(getattr(analysis, "operations", ()))
    payload_operations = [
        _operation_payload(batch, operation, operation_index)
        for operation_index, operation in enumerate(operations)
    ]
    result = apply_memory_operation_batch(
        {
            "user_id": batch.user_id,
            "conversation_id": batch.conversation_id,
            "batch_key": batch.batch_key,
            "operations": payload_operations,
        }
    )
    return MemoryApplicationResult(
        batch_key=batch.batch_key,
        idempotent=bool(result["idempotent"]),
        applied_count=int(result["applied_count"]),
        deferred_count=int(result["deferred_count"]),
        operations=tuple(result["operations"]),
    )


def _operation_payload(
    batch: MemoryBatch,
    operation: MemoryOperation,
    operation_index: int,
) -> dict[str, Any]:
    evidence_by_index = {
        message.message_index: message.content
        for message in batch.messages
        if message.evidence_eligible
    }
    try:
        evidence = [
            {
                "conversation_id": batch.conversation_id,
                "message_index": message_index,
                "text": evidence_by_index[message_index],
            }
            for message_index in operation.evidence_message_indexes
        ]
    except KeyError as error:
        raise ValueError("memory operation requires eligible user evidence") from error
    if not evidence:
        raise ValueError("memory operation requires eligible user evidence")

    operation_payload = {
        "operation": operation.operation,
        "target_memory_id": operation.target_memory_id,
        "data_point_type": operation.data_point_type,
        "category": operation.category,
        "key": operation.key,
        "label": operation.label,
        "value": operation.value,
        "confidence": operation.confidence,
        "evidence": evidence,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            operation_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "operation_index": operation_index,
        "operation_fingerprint": fingerprint,
        **operation_payload,
    }


__all__ = [
    "MemoryApplicationResult",
    "apply_validated_memory_analysis",
    "memory_background_v2_live_writes_enabled",
]
