"""Delegates combined model output to memory and thread domain validators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.context_engine.conversation_engine.state import evaluate_thread_operation_shadow
from agent.memory_engine.processing.models import MemoryBatch


@dataclass(frozen=True)
class BackgroundCognitionAnalysis:
    """Validated memory and thread lanes from one provider response."""

    decision: str
    memory: Any
    thread: dict[str, Any]
    thread_operation: str
    valid: bool
    errors: tuple[str, ...] = ()


def validate_background_cognition_analysis(
    raw: Any,
    *,
    batch: MemoryBatch,
    existing_memory_ids: set[str],
    thread_candidates: list[dict[str, object]],
) -> BackgroundCognitionAnalysis:
    """Validate the envelope once, then delegate each domain-specific lane."""
    # Imported lazily so the existing memory worker can call this coordinator
    # without creating a module-import cycle.
    from agent.memory_engine.processing.shadow import validate_shadow_memory_analysis

    errors: list[str] = []
    if not isinstance(raw, dict):
        raw = {}
        errors.append("background cognition analysis must be an object")
    unknown = set(raw) - {"decision", "operations", "thread_operation", "handoff"}
    if unknown:
        errors.append(f"unsupported top-level fields: {', '.join(sorted(unknown))}")

    decision = raw.get("decision")
    operations = raw.get("operations")
    thread_operation = raw.get("thread_operation")
    operation_name = (
        str(thread_operation.get("operation"))
        if isinstance(thread_operation, dict)
        else "invalid"
    )
    if decision not in {"propose", "no_change"}:
        errors.append("decision must be propose or no_change")
    has_memory_change = isinstance(operations, list) and bool(operations)
    has_thread_change = operation_name not in {"none", "invalid"}
    if decision == "no_change" and (has_memory_change or has_thread_change):
        errors.append("no_change cannot include memory or thread operations")
    if decision == "propose" and not (has_memory_change or has_thread_change):
        errors.append("propose requires a memory or thread operation")

    memory_raw = {
        "decision": "propose" if has_memory_change else "no_change",
        "operations": operations if isinstance(operations, list) else operations,
        "handoff": raw.get("handoff"),
    }
    memory = validate_shadow_memory_analysis(
        memory_raw,
        batch=batch,
        existing_memory_ids=existing_memory_ids,
    )
    candidate_ids = {
        str(candidate["id"])
        for candidate in thread_candidates
        if isinstance(candidate, dict) and candidate.get("id")
    }
    thread = evaluate_thread_operation_shadow(
        thread_operation,
        conversation_id=batch.conversation_id,
        user_id=batch.user_id,
        message_index=batch.new_end_message_index,
        candidate_thread_ids=candidate_ids,
    )
    errors.extend(f"memory: {error}" for error in memory.errors)
    errors.extend(f"thread: {error}" for error in thread.get("errors") or [])
    return BackgroundCognitionAnalysis(
        decision=str(decision or "invalid"),
        memory=memory,
        thread=thread,
        thread_operation=operation_name,
        valid=not errors and memory.valid and bool(thread.get("valid")),
        errors=tuple(errors),
    )


__all__ = ["BackgroundCognitionAnalysis", "validate_background_cognition_analysis"]
