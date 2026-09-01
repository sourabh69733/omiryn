"""Pure fail-closed validation for v3 background-memory proposals."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.memory_engine.processing.models import MemoryBatch, MemoryHandoff
from agent.shared.utils import is_non_empty_string, is_number, unknown_fields

from .models import MemoryKind, MemoryPurpose, MemorySensitivity
from .operations import MemoryAddProposal, MemoryAnalysisV3


MAX_MEMORY_OPERATIONS = 12
_OPERATION_FIELDS = {
    "operation",
    "memory_kind",
    "purposes",
    "key",
    "value",
    "sensitivity",
    "confidence",
    "importance",
    "occurred_at",
    "valid_from",
    "valid_until",
    "evidence_message_indexes",
}


def validate_memory_analysis_v3(raw: Any, *, batch: MemoryBatch) -> MemoryAnalysisV3:
    """Validate v3 additions without interpreting natural-language content."""
    if not isinstance(raw, dict):
        return _invalid("memory analysis must be an object", batch.previous_handoff)
    errors: list[str] = []
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

    operations: list[MemoryAddProposal] = []
    eligible_indexes = set(batch.evidence_message_indexes)
    for index, raw_operation in enumerate(raw_operations[:MAX_MEMORY_OPERATIONS]):
        operation, operation_errors = _validate_add(
            raw_operation,
            eligible_indexes=eligible_indexes,
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
        return MemoryAnalysisV3(
            decision=str(decision or "invalid"),
            operations=(),
            handoff=batch.previous_handoff,
            valid=False,
            errors=tuple(errors),
        )
    return MemoryAnalysisV3(
        decision=str(decision),
        operations=tuple(operations),
        handoff=handoff,
        valid=True,
    )


def _validate_add(
    raw: Any,
    *,
    eligible_indexes: set[int],
) -> tuple[MemoryAddProposal | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["operation must be an object"]
    errors: list[str] = []
    unsupported = unknown_fields(raw, _OPERATION_FIELDS)
    if unsupported:
        errors.append(f"unsupported fields: {', '.join(unsupported)}")
    if raw.get("operation") != "add":
        errors.append("v3 currently supports only add operations")

    kind = _enum_value(MemoryKind, raw.get("memory_kind"), "memory_kind", errors)
    sensitivity = _enum_value(
        MemorySensitivity,
        raw.get("sensitivity"),
        "sensitivity",
        errors,
    )
    purposes = _purposes(raw.get("purposes"), errors)
    key = raw.get("key")
    if not is_non_empty_string(key) or len(str(key)) > 160:
        errors.append("key must be a non-empty string of at most 160 characters")
    value = raw.get("value")
    if value is None or isinstance(value, bool):
        errors.append("value must contain useful data")

    confidence = _score(raw.get("confidence"), "confidence", errors)
    importance = _score(raw.get("importance"), "importance", errors)
    occurred_at = _optional_datetime(raw.get("occurred_at"), "occurred_at", errors)
    valid_from = _optional_datetime(raw.get("valid_from"), "valid_from", errors)
    valid_until = _optional_datetime(raw.get("valid_until"), "valid_until", errors)
    if valid_from and valid_until and valid_until < valid_from:
        errors.append("valid_until cannot precede valid_from")

    evidence_indexes = _evidence_indexes(
        raw.get("evidence_message_indexes"),
        eligible_indexes,
        errors,
    )
    if errors or kind is None or sensitivity is None:
        return None, errors
    return MemoryAddProposal(
        kind=kind,
        purposes=purposes,
        key=str(key).strip(),
        value=value,
        sensitivity=sensitivity,
        confidence=confidence,
        importance=importance,
        evidence_message_indexes=evidence_indexes,
        occurred_at=occurred_at,
        valid_from=valid_from,
        valid_until=valid_until,
    ), []


def _purposes(value: Any, errors: list[str]) -> frozenset[MemoryPurpose]:
    if not isinstance(value, list) or not value:
        errors.append("purposes must be a non-empty array")
        return frozenset()
    try:
        purposes = frozenset(MemoryPurpose(str(item)) for item in value)
    except ValueError:
        errors.append("purposes contains an unsupported value")
        return frozenset()
    if len(purposes) != len(value):
        errors.append("purposes cannot contain duplicates")
    return purposes


def _enum_value(enum_type, value: Any, name: str, errors: list[str]):
    try:
        return enum_type(str(value))
    except ValueError:
        errors.append(f"{name} contains an unsupported value")
        return None


def _score(value: Any, name: str, errors: list[str]) -> float:
    if not is_number(value) or not 0 <= float(value) <= 1:
        errors.append(f"{name} must be between 0 and 1")
        return 0.0
    return float(value)


def _optional_datetime(value: Any, name: str, errors: list[str]) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"{name} must be an ISO-8601 string or null")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{name} must be a valid ISO-8601 string")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{name} must include a timezone")
        return None
    return parsed


def _evidence_indexes(
    value: Any,
    eligible_indexes: set[int],
    errors: list[str],
) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        errors.append("evidence_message_indexes must be a non-empty array")
        return ()
    indexes = tuple(item for item in value if isinstance(item, int) and not isinstance(item, bool))
    if len(indexes) != len(value):
        errors.append("evidence_message_indexes must contain only integers")
    if len(set(indexes)) != len(indexes):
        errors.append("evidence_message_indexes cannot contain duplicates")
    invalid = set(indexes) - eligible_indexes
    if invalid:
        errors.append(
            "evidence contains ineligible message indexes: "
            + ", ".join(str(item) for item in sorted(invalid))
        )
    return indexes


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


def _invalid(error: str, handoff: MemoryHandoff) -> MemoryAnalysisV3:
    return MemoryAnalysisV3(
        decision="invalid",
        operations=(),
        handoff=handoff,
        valid=False,
        errors=(error,),
    )


__all__ = ["MAX_MEMORY_OPERATIONS", "validate_memory_analysis_v3"]
