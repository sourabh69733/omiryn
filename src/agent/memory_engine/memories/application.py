"""Maps validated v3 lifecycle proposals to one atomic storage transaction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from storage.memories import apply_agent_memory_operation_batch

from agent.memory_engine.processing.models import MemoryBatch
from agent.shared.clock import utc_now

from .operations import (
    MemoryAddProposal,
    MemoryAnalysisV3,
    MemoryProposalV3,
    MemoryReinforceProposal,
    MemoryRetractProposal,
    MemorySupersedeProposal,
)


@dataclass(frozen=True)
class MemoryApplicationResultV3:
    batch_key: str
    idempotent: bool
    applied_count: int
    deferred_count: int = 0
    memories: tuple[dict[str, Any], ...] = ()


def apply_validated_memory_analysis_v3(
    batch: MemoryBatch,
    analysis: MemoryAnalysisV3,
    *,
    extractor_model: str | None,
) -> MemoryApplicationResultV3:
    """Resolve trusted evidence and apply the complete lifecycle batch once."""
    if not analysis.valid:
        raise ValueError("live writes require a validated v3 memory analysis")
    observed_at = utc_now()
    operations = [
        _operation_payload(
            batch,
            operation,
            operation_index,
            observed_at=observed_at,
            extractor_model=extractor_model,
        )
        for operation_index, operation in enumerate(analysis.operations)
    ]
    result = apply_agent_memory_operation_batch(
        {
            "user_id": batch.user_id,
            "conversation_id": batch.conversation_id,
            "batch_key": batch.batch_key,
            "operations": operations,
        }
    )
    return MemoryApplicationResultV3(
        batch_key=batch.batch_key,
        idempotent=bool(result["idempotent"]),
        applied_count=int(result["applied_count"]),
        deferred_count=int(result.get("deferred_count") or 0),
        memories=tuple(result["memories"]),
    )


def _operation_payload(
    batch: MemoryBatch,
    proposal: MemoryProposalV3,
    operation_index: int,
    *,
    observed_at: datetime,
    extractor_model: str | None,
) -> dict[str, Any]:
    if isinstance(proposal, MemoryAddProposal):
        payload = {
            "operation": "add",
            "memory": _memory_payload(
                batch,
                proposal,
                observed_at=observed_at,
                extractor_model=extractor_model,
            ),
        }
    elif isinstance(proposal, MemoryReinforceProposal):
        payload = {
            "operation": "reinforce",
            "target_memory_id": proposal.target_memory_id,
            "confidence": proposal.confidence,
            "importance": proposal.importance,
            "evidence": _trusted_evidence(batch, proposal.evidence_message_indexes, observed_at),
        }
    elif isinstance(proposal, MemorySupersedeProposal):
        payload = {
            "operation": "supersede",
            "target_memory_id": proposal.target_memory_id,
            "memory": {
                **_memory_payload(
                    batch,
                    proposal.replacement,
                    observed_at=observed_at,
                    extractor_model=extractor_model,
                ),
                "supersedes_memory_id": proposal.target_memory_id,
            },
        }
    elif isinstance(proposal, MemoryRetractProposal):
        payload = {
            "operation": "retract",
            "target_memory_id": proposal.target_memory_id,
            "evidence": _trusted_evidence(batch, proposal.evidence_message_indexes, observed_at),
        }
    else:  # pragma: no cover - the closed proposal union prevents this.
        raise TypeError("unsupported v3 memory proposal")

    fingerprint_payload = _without_observation_time(payload)
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "operation_index": operation_index,
        "operation_fingerprint": fingerprint,
        **payload,
    }


def _memory_payload(
    batch: MemoryBatch,
    proposal: MemoryAddProposal,
    *,
    observed_at: datetime,
    extractor_model: str | None,
) -> dict[str, Any]:
    return {
        "kind": proposal.kind.value,
        "purposes": sorted(purpose.value for purpose in proposal.purposes),
        "key": proposal.key,
        "value": proposal.value,
        # A model may describe utility, but it cannot grant matching permission.
        "allowed_uses": ["reply_context"],
        "sensitivity": proposal.sensitivity.value,
        "confidence": proposal.confidence,
        "importance": proposal.importance,
        "occurred_at": _isoformat(proposal.occurred_at),
        "valid_from": _isoformat(proposal.valid_from),
        "valid_until": _isoformat(proposal.valid_until),
        "extractor": "background_cognition_v3",
        "extractor_model": extractor_model,
        "evidence": _trusted_evidence(batch, proposal.evidence_message_indexes, observed_at),
    }


def _trusted_evidence(
    batch: MemoryBatch,
    message_indexes: tuple[int, ...],
    observed_at: datetime,
) -> list[dict[str, Any]]:
    evidence_by_index = {
        message.message_index: message.content
        for message in batch.messages
        if message.evidence_eligible
    }
    try:
        return [
            {
                "conversation_id": batch.conversation_id,
                "message_index": message_index,
                "exact_quote": evidence_by_index[message_index],
                "observed_at": observed_at.isoformat(),
            }
            for message_index in message_indexes
        ]
    except KeyError as error:
        raise ValueError("v3 memory requires eligible user evidence") from error


def _without_observation_time(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_observation_time(item)
            for key, item in value.items()
            if key != "observed_at"
        }
    if isinstance(value, list):
        return [_without_observation_time(item) for item in value]
    return value


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = [
    "MemoryApplicationResultV3",
    "apply_validated_memory_analysis_v3",
]
