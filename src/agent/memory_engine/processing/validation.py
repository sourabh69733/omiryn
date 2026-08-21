"""Pure validation for model-proposed memory operations and handoffs."""

from __future__ import annotations

from typing import Any

from agent.shared.utils import is_non_empty_string, is_number, unknown_fields

from .models import MemoryBatch, MemoryHandoff, MemoryOperation, MemoryAnalysis


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
MAX_MEMORY_OPERATIONS = 12


def validate_memory_analysis(
    raw: Any,
    *,
    batch: MemoryBatch,
    existing_memory_ids: set[str],
) -> MemoryAnalysis:
    """Reject the complete result when any memory operation is unsafe."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return _invalid("memory analysis must be an object", batch.previous_handoff)
    unsupported = unknown_fields(raw, {"decision", "operations", "handoff"})
    if unsupported:
        errors.append(f"unsupported top-level fields: {', '.join(unsupported)}")
    decision = raw.get("decision")
    if decision not in {"propose", "no_change"}:
        errors.append("decision must be propose or no_change")

    raw_operations = raw.get("operations")
    if not isinstance(raw_operations, list):
        errors.append("operations must be an array")
        raw_operations = []
    if len(raw_operations) > MAX_MEMORY_OPERATIONS:
        errors.append(f"operations cannot contain more than {MAX_MEMORY_OPERATIONS} items")

    eligible_indexes = set(batch.evidence_message_indexes)
    operations: list[MemoryOperation] = []
    for index, raw_operation in enumerate(raw_operations[:MAX_MEMORY_OPERATIONS]):
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
        return MemoryAnalysis(
            decision=str(decision or "invalid"),
            operations=(),
            handoff=batch.previous_handoff,
            valid=False,
            errors=tuple(errors),
        )
    return MemoryAnalysis(
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
    unsupported = unknown_fields(raw, _OPERATION_FIELDS)
    if unsupported:
        errors.append(f"unsupported fields: {', '.join(unsupported)}")
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
        for field_name, field_value in (("category", category), ("key", key), ("label", label)):
            if not is_non_empty_string(field_value):
                errors.append(f"{field_name} must be a non-empty string")
        if value is None or isinstance(value, bool):
            errors.append("value must contain useful data")
    if confidence is not None and (not is_number(confidence) or not 0 <= float(confidence) <= 1):
        errors.append("confidence must be between 0 and 1")
    if requires_value and confidence is None:
        errors.append("confidence is required")

    raw_evidence = raw.get("evidence_message_indexes")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        errors.append("evidence_message_indexes must be a non-empty array")
        evidence_indexes: tuple[int, ...] = ()
    else:
        evidence_indexes = tuple(
            item for item in raw_evidence if isinstance(item, int) and not isinstance(item, bool)
        )
        if len(evidence_indexes) != len(raw_evidence):
            errors.append("evidence_message_indexes must contain only integers")
        if len(set(evidence_indexes)) != len(evidence_indexes):
            errors.append("evidence_message_indexes cannot contain duplicates")
        invalid_evidence = set(evidence_indexes) - eligible_indexes
        if invalid_evidence:
            errors.append(
                "evidence contains ineligible message indexes: "
                + ", ".join(str(item) for item in sorted(invalid_evidence))
            )

    if errors:
        return None, errors
    return MemoryOperation(
        operation=operation,
        target_memory_id=target_memory_id,
        data_point_type=data_point_type,
        category=category,
        key=key,
        label=label,
        value=value,
        confidence=float(confidence) if confidence is not None else None,
        evidence_message_indexes=evidence_indexes,
    ), []


def _validate_handoff(raw: Any) -> tuple[MemoryHandoff, list[str]]:
    if not isinstance(raw, dict):
        return MemoryHandoff(), ["must be an object"]
    errors: list[str] = []
    unsupported = unknown_fields(
        raw,
        {"summary", "active_people", "active_topics", "unresolved_references"},
    )
    if unsupported:
        errors.append(f"unsupported fields: {', '.join(unsupported)}")
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
        if any(not is_non_empty_string(item) or len(item) > 160 for item in raw_values):
            errors.append(f"{name} contains an invalid string")
        values[name] = tuple(item.strip() for item in raw_values if isinstance(item, str))
    return MemoryHandoff(
        summary=summary,
        active_people=values.get("active_people", ()),
        active_topics=values.get("active_topics", ()),
        unresolved_references=values.get("unresolved_references", ()),
    ), errors


def _invalid(error: str, handoff: MemoryHandoff) -> MemoryAnalysis:
    return MemoryAnalysis(
        decision="invalid",
        operations=(),
        handoff=handoff,
        valid=False,
        errors=(error,),
    )


__all__ = [
    "MAX_MEMORY_OPERATIONS",
    "MemoryAnalysis",
    "validate_memory_analysis",
]
