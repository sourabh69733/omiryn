"""Runs background memory analysis in observation-only shadow mode."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any

from agent.providers import analyze_memory_batch
from storage import list_data_point_extraction_debug, list_profile_facts
from storage.profile_facts import save_data_point_extraction_debug

from .context import DEFAULT_CONTEXT_OVERLAP, build_memory_batch
from .models import MemoryBatch, MemoryHandoff, MemoryOperation, MemoryProcessingState
from .prompt import memory_batch_prompt
from .service import get_processing_state, save_processing_state

_ALLOWED_DATA_POINT_TYPES = {
    "profile_fact",
    "matching_fact",
    "chat_learning",
    "temporary_context",
}
_ALLOWED_OPERATIONS = {"add", "reinforce", "supersede", "retract"}
_OPERATION_FIELDS = {
    "operation",
    "target_memory_id",
    "data_point_type",
    "category",
    "key",
    "label",
    "value",
    "confidence",
    "evidence_message_indexes",
}
MAX_SHADOW_OPERATIONS = 12
MAX_EXISTING_MEMORIES = 8


@dataclass(frozen=True)
class ShadowMemoryAnalysis:
    """Validated observation-only result returned by the shadow worker."""

    decision: str
    operations: tuple[MemoryOperation, ...]
    handoff: MemoryHandoff
    valid: bool
    errors: tuple[str, ...] = ()


def memory_background_v2_shadow_enabled() -> bool:
    return os.getenv("MEMORY_BACKGROUND_V2_SHADOW", "true").strip().lower() == "true"


def memory_background_v2_threshold() -> int:
    try:
        return max(1, int(os.getenv("MEMORY_BACKGROUND_V2_THRESHOLD", "7")))
    except ValueError:
        return 7


def should_schedule_shadow_memory_extraction(
    conversation_id: str,
    user_id: str | None,
    messages: list[dict[str, object]],
    quality_valid: bool,
) -> bool:
    """Schedule only complete threshold batches; idle flushing arrives later."""
    if not memory_background_v2_shadow_enabled() or not user_id or not quality_valid:
        return False
    state = get_processing_state(conversation_id, user_id)
    threshold = memory_background_v2_threshold()
    batch = build_memory_batch(
        conversation_id=conversation_id,
        user_id=user_id,
        messages=messages,
        state=state,
        context_overlap=_context_overlap(),
        max_meaningful_user_messages=threshold,
    )
    return bool(batch and batch.meaningful_user_message_count >= threshold)


async def run_shadow_memory_extraction(
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, object]],
    model: str | None = None,
) -> dict[str, Any]:
    """Analyze and record one batch without modifying live memories or threads."""
    state = get_processing_state(conversation_id, user_id)
    batch = build_memory_batch(
        conversation_id=conversation_id,
        user_id=user_id,
        messages=messages,
        state=state,
        context_overlap=_context_overlap(),
        max_meaningful_user_messages=memory_background_v2_threshold(),
    )
    if batch is None:
        return {"status": "no_pending_messages", "operation_count": 0}

    existing_memories = _existing_memory_context(user_id)
    try:
        raw = await analyze_memory_batch(
            memory_batch_prompt(batch, existing_memories),
            conversation_id=conversation_id,
            model=os.getenv("MEMORY_BACKGROUND_V2_MODEL", "").strip() or model,
            timeout_seconds=_timeout_seconds(),
        )
        analysis = validate_shadow_memory_analysis(
            raw,
            batch=batch,
            existing_memory_ids={str(memory["id"]) for memory in existing_memories},
        )
        next_handoff = analysis.handoff if analysis.valid else batch.previous_handoff
        current_state = state or MemoryProcessingState(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        saved_state = save_processing_state(
            replace(
                current_state,
                processed_through_message_index=batch.new_end_message_index,
                last_batch_key=batch.batch_key,
                handoff=next_handoff,
            )
        )
        decision = "shadow_valid" if analysis.valid else "shadow_invalid"
        _save_shadow_debug_once(
            batch=batch,
            decision=decision,
            candidate={
                "model_decision": analysis.decision,
                "operations": [_operation_dict(operation) for operation in analysis.operations],
                "handoff": _handoff_dict(analysis.handoff),
            },
            review={
                "valid": analysis.valid,
                "errors": list(analysis.errors),
                "live_writes": False,
            },
            state_version=saved_state.version,
        )
        return {
            "status": decision,
            "batch_key": batch.batch_key,
            "operation_count": len(analysis.operations),
            "errors": list(analysis.errors),
            "processed_through_message_index": saved_state.processed_through_message_index,
        }
    except Exception as error:
        _save_shadow_debug_once(
            batch=batch,
            decision="shadow_error",
            candidate={},
            review={
                "valid": False,
                "errors": [f"{type(error).__name__}: {str(error)[:300]}"],
                "live_writes": False,
            },
            state_version=state.version if state else 0,
        )
        return {
            "status": "shadow_error",
            "batch_key": batch.batch_key,
            "operation_count": 0,
            "errors": [f"{type(error).__name__}: {str(error)[:300]}"],
        }


def validate_shadow_memory_analysis(
    raw: Any,
    *,
    batch: MemoryBatch,
    existing_memory_ids: set[str],
) -> ShadowMemoryAnalysis:
    """Reject a complete model result if any operation exceeds trusted boundaries."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return _invalid("memory analysis must be an object", batch.previous_handoff)
    unknown = set(raw) - {"decision", "operations", "handoff"}
    if unknown:
        errors.append(f"unsupported top-level fields: {', '.join(sorted(unknown))}")
    decision = raw.get("decision")
    if decision not in {"propose", "no_change"}:
        errors.append("decision must be propose or no_change")

    raw_operations = raw.get("operations")
    if not isinstance(raw_operations, list):
        errors.append("operations must be an array")
        raw_operations = []
    if len(raw_operations) > MAX_SHADOW_OPERATIONS:
        errors.append(f"operations cannot contain more than {MAX_SHADOW_OPERATIONS} items")

    eligible_indexes = set(batch.evidence_message_indexes)
    operations: list[MemoryOperation] = []
    for index, raw_operation in enumerate(raw_operations[:MAX_SHADOW_OPERATIONS]):
        operation, operation_errors = _validate_operation(
            raw_operation,
            eligible_indexes=eligible_indexes,
            existing_memory_ids=existing_memory_ids,
        )
        errors.extend(f"operations[{index}]: {error}" for error in operation_errors)
        if operation is not None:
            operations.append(operation)

    if decision == "no_change" and raw_operations:
        errors.append("no_change cannot include operations")
    if decision == "propose" and not raw_operations:
        errors.append("propose requires at least one operation")

    handoff, handoff_errors = _validate_handoff(raw.get("handoff"))
    errors.extend(f"handoff: {error}" for error in handoff_errors)
    if errors:
        return ShadowMemoryAnalysis(
            decision=str(decision or "invalid"),
            operations=(),
            handoff=batch.previous_handoff,
            valid=False,
            errors=tuple(errors),
        )
    return ShadowMemoryAnalysis(
        decision=str(decision),
        operations=tuple(operations),
        handoff=handoff,
        valid=True,
    )


def _validate_operation(
    raw: Any,
    *,
    eligible_indexes: set[int],
    existing_memory_ids: set[str],
) -> tuple[MemoryOperation | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["operation must be an object"]
    errors: list[str] = []
    unknown = set(raw) - _OPERATION_FIELDS
    if unknown:
        errors.append(f"unsupported fields: {', '.join(sorted(unknown))}")
    operation = raw.get("operation")
    if operation not in _ALLOWED_OPERATIONS:
        errors.append("unsupported operation")

    target_memory_id = raw.get("target_memory_id")
    if operation == "add":
        if target_memory_id is not None:
            errors.append("add cannot include target_memory_id")
    elif operation in {"reinforce", "supersede", "retract"}:
        if not isinstance(target_memory_id, str) or target_memory_id not in existing_memory_ids:
            errors.append("operation requires a supplied existing target_memory_id")

    requires_value = operation in {"add", "supersede"}
    data_point_type = raw.get("data_point_type")
    category = raw.get("category")
    key = raw.get("key")
    label = raw.get("label")
    value = raw.get("value")
    confidence = raw.get("confidence")
    if requires_value:
        if data_point_type not in _ALLOWED_DATA_POINT_TYPES:
            errors.append("unsupported data_point_type")
        for field_name, field_value in (
            ("category", category),
            ("key", key),
            ("label", label),
        ):
            if not isinstance(field_value, str) or not field_value.strip():
                errors.append(f"{field_name} must be a non-empty string")
        if value is None or isinstance(value, bool):
            errors.append("value must contain useful data")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        errors.append("confidence must be between 0 and 1")
    if requires_value and confidence is None:
        errors.append("confidence is required")

    raw_evidence = raw.get("evidence_message_indexes")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        errors.append("evidence_message_indexes must be a non-empty array")
        evidence_indexes: tuple[int, ...] = ()
    else:
        evidence_indexes = tuple(
            value for value in raw_evidence if isinstance(value, int) and not isinstance(value, bool)
        )
        if len(evidence_indexes) != len(raw_evidence):
            errors.append("evidence_message_indexes must contain only integers")
        if len(set(evidence_indexes)) != len(evidence_indexes):
            errors.append("evidence_message_indexes cannot contain duplicates")
        invalid_evidence = set(evidence_indexes) - eligible_indexes
        if invalid_evidence:
            errors.append(
                "evidence contains ineligible message indexes: "
                + ", ".join(str(value) for value in sorted(invalid_evidence))
            )

    if errors:
        return None, errors
    return (
        MemoryOperation(
            operation=operation,
            target_memory_id=target_memory_id,
            data_point_type=data_point_type,
            category=category,
            key=key,
            label=label,
            value=value,
            confidence=float(confidence) if confidence is not None else None,
            evidence_message_indexes=evidence_indexes,
        ),
        [],
    )


def _validate_handoff(raw: Any) -> tuple[MemoryHandoff, list[str]]:
    if not isinstance(raw, dict):
        return MemoryHandoff(), ["must be an object"]
    errors: list[str] = []
    unknown = set(raw) - {
        "summary",
        "active_people",
        "active_topics",
        "unresolved_references",
    }
    if unknown:
        errors.append(f"unsupported fields: {', '.join(sorted(unknown))}")
    summary = raw.get("summary")
    if not isinstance(summary, str) or len(summary) > 2000:
        errors.append("summary must be a string of at most 2000 characters")
        summary = ""
    values: dict[str, tuple[str, ...]] = {}
    for name in ("active_people", "active_topics", "unresolved_references"):
        raw_values = raw.get(name)
        if not isinstance(raw_values, list) or len(raw_values) > 20:
            errors.append(f"{name} must be an array of at most 20 strings")
            values[name] = ()
            continue
        if any(
            not isinstance(value, str) or not value.strip() or len(value) > 160
            for value in raw_values
        ):
            errors.append(f"{name} contains an invalid string")
        values[name] = tuple(value.strip() for value in raw_values if isinstance(value, str))
    return (
        MemoryHandoff(
            summary=summary,
            active_people=values.get("active_people", ()),
            active_topics=values.get("active_topics", ()),
            unresolved_references=values.get("unresolved_references", ()),
        ),
        errors,
    )


def _invalid(error: str, handoff: MemoryHandoff) -> ShadowMemoryAnalysis:
    return ShadowMemoryAnalysis(
        decision="invalid",
        operations=(),
        handoff=handoff,
        valid=False,
        errors=(error,),
    )


def _existing_memory_context(user_id: str) -> list[dict[str, Any]]:
    memories = list_profile_facts(user_id, statuses={"active"})
    memories.sort(key=lambda memory: str(memory.get("updated_at") or ""), reverse=True)
    return [
        {
            "id": memory["id"],
            "data_point_type": memory["fact_type"],
            "category": memory["category"],
            "key": memory["key"],
            "label": memory["label"],
            "value": memory["value"],
            "confidence": memory["confidence"],
        }
        for memory in memories[:MAX_EXISTING_MEMORIES]
    ]


def _save_shadow_debug_once(
    *,
    batch: MemoryBatch,
    decision: str,
    candidate: dict[str, Any],
    review: dict[str, Any],
    state_version: int,
) -> None:
    candidate_key = f"memory_shadow:{batch.batch_key}:{decision}"
    existing = list_data_point_extraction_debug(
        user_id=batch.user_id,
        source_id=batch.conversation_id,
        limit=100,
    )
    if any(row.get("candidate_key") == candidate_key for row in existing):
        return
    save_data_point_extraction_debug(
        {
            "user_id": batch.user_id,
            "source_kind": "agent_conversation",
            "source_id": batch.conversation_id,
            "import_id": None,
            "candidate_key": candidate_key,
            "decision": decision,
            "candidate": candidate,
            "review": review,
            "metadata": {
                "title": "Background memory shadow",
                "extractor": "memory_background_v2_shadow",
                "batch_key": batch.batch_key,
                "new_start_message_index": batch.new_start_message_index,
                "new_end_message_index": batch.new_end_message_index,
                "context_message_indexes": [
                    message.message_index for message in batch.context_messages
                ],
                "evidence_eligible_message_indexes": list(batch.evidence_message_indexes),
                "state_version": state_version,
                "live_writes": False,
            },
        }
    )


def _operation_dict(operation: MemoryOperation) -> dict[str, Any]:
    return {
        "operation": operation.operation,
        "target_memory_id": operation.target_memory_id,
        "data_point_type": operation.data_point_type,
        "category": operation.category,
        "key": operation.key,
        "label": operation.label,
        "value": operation.value,
        "confidence": operation.confidence,
        "evidence_message_indexes": list(operation.evidence_message_indexes),
    }


def _handoff_dict(handoff: MemoryHandoff) -> dict[str, Any]:
    return {
        "summary": handoff.summary,
        "active_people": list(handoff.active_people),
        "active_topics": list(handoff.active_topics),
        "unresolved_references": list(handoff.unresolved_references),
    }


def _context_overlap() -> int:
    try:
        return max(0, int(os.getenv("MEMORY_BACKGROUND_V2_CONTEXT_OVERLAP", "12")))
    except ValueError:
        return DEFAULT_CONTEXT_OVERLAP


def _timeout_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("MEMORY_BACKGROUND_V2_TIMEOUT_SECONDS", "120")))
    except ValueError:
        return 120.0


__all__ = [
    "ShadowMemoryAnalysis",
    "memory_background_v2_shadow_enabled",
    "run_shadow_memory_extraction",
    "should_schedule_shadow_memory_extraction",
    "validate_shadow_memory_analysis",
]
