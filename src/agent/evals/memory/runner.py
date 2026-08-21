"""Runs memory scenarios through the real background prompt and deterministic grader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from agent.evals.behavior.core.events import EventSink, emit_event
from agent.memory_engine.processing import MemoryProcessingState, build_memory_batch
from agent.memory_engine.processing.prompt import memory_batch_prompt
from agent.memory_engine.processing.shadow import validate_shadow_memory_analysis
from agent.providers import analyze_memory_batch
from storage import save_conversation

from .scenarios import ExpectedMemoryOperation, MemoryShadowScenario


@dataclass(frozen=True)
class MemoryScenarioResult:
    """Expected-versus-observed result for one background memory batch."""

    scenario_id: str
    passed: bool
    decision: str
    operations: tuple[dict[str, Any], ...]
    structurally_valid: bool
    validation_errors: tuple[str, ...]
    findings: tuple[str, ...]
    raw_response: dict[str, Any] | None
    duration_seconds: float
    error: str | None = None


async def run_memory_shadow_scenario(
    *,
    scenario: MemoryShadowScenario,
    model: str | None,
    timeout_seconds: float,
    event_sink: EventSink | None = None,
) -> MemoryScenarioResult:
    """Call the configured provider once and grade its validated shadow proposal."""
    conversation_id = f"memory-eval-{scenario.id}-{uuid4().hex}"
    user_id = f"memory-eval-user-{scenario.id}"
    state = (
        MemoryProcessingState(
            conversation_id=conversation_id,
            user_id=user_id,
            processed_through_message_index=scenario.processed_through_message_index,
            handoff=scenario.previous_handoff,
        )
        if scenario.processed_through_message_index >= 0 or scenario.previous_handoff.summary
        or scenario.previous_handoff.active_people
        or scenario.previous_handoff.active_topics
        or scenario.previous_handoff.unresolved_references
        else None
    )
    batch = build_memory_batch(
        conversation_id=conversation_id,
        user_id=user_id,
        messages=[dict(message) for message in scenario.messages],
        state=state,
    )
    if batch is None:
        return MemoryScenarioResult(
            scenario_id=scenario.id,
            passed=False,
            decision="error",
            operations=(),
            structurally_valid=False,
            validation_errors=("Scenario produced no pending batch.",),
            findings=("Scenario produced no pending batch.",),
            raw_response=None,
            duration_seconds=0,
            error="Scenario produced no pending batch.",
        )
    save_conversation(
        {
            "id": conversation_id,
            "status": "active",
            "messages": [dict(message) for message in scenario.messages],
            "agent_model": model,
        },
        user_id,
    )
    existing_memories = [memory.as_context() for memory in scenario.existing_memories]
    emit_event(
        event_sink,
        "memory_scenario_started",
        "Memory scenario started.",
        scenario_id=scenario.id,
        expected_decision=scenario.expected_decision,
    )
    emit_event(
        event_sink,
        "memory_call_started",
        "Background memory model call started.",
        scenario_id=scenario.id,
        model_name=model or "provider-default",
    )
    started = perf_counter()
    try:
        raw = await analyze_memory_batch(
            memory_batch_prompt(batch, existing_memories),
            conversation_id=conversation_id,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except Exception as error:
        duration = round(perf_counter() - started, 3)
        message = f"{type(error).__name__}: {error}"
        emit_event(
            event_sink,
            "memory_call_failed",
            "Background memory model call failed.",
            scenario_id=scenario.id,
            error=message,
            duration_seconds=duration,
        )
        return MemoryScenarioResult(
            scenario_id=scenario.id,
            passed=False,
            decision="error",
            operations=(),
            structurally_valid=False,
            validation_errors=(),
            findings=(message,),
            raw_response=None,
            duration_seconds=duration,
            error=message,
        )
    duration = round(perf_counter() - started, 3)
    emit_event(
        event_sink,
        "memory_call_completed",
        "Background memory model call completed.",
        scenario_id=scenario.id,
        duration_seconds=duration,
    )
    analysis = validate_shadow_memory_analysis(
        raw,
        batch=batch,
        existing_memory_ids={memory.id for memory in scenario.existing_memories},
    )
    operations = tuple(_operation_payload(operation) for operation in analysis.operations)
    passed, findings = grade_memory_shadow_result(
        scenario=scenario,
        decision=analysis.decision,
        operations=operations,
        structurally_valid=analysis.valid,
        validation_errors=analysis.errors,
    )
    emit_event(
        event_sink,
        "memory_scenario_completed",
        "Memory scenario completed.",
        scenario_id=scenario.id,
        passed=passed,
        operation_count=len(operations),
        findings=list(findings),
    )
    return MemoryScenarioResult(
        scenario_id=scenario.id,
        passed=passed,
        decision=analysis.decision,
        operations=operations,
        structurally_valid=analysis.valid,
        validation_errors=analysis.errors,
        findings=findings,
        raw_response=raw,
        duration_seconds=duration,
    )


def grade_memory_shadow_result(
    *,
    scenario: MemoryShadowScenario,
    decision: str,
    operations: tuple[dict[str, Any], ...],
    structurally_valid: bool,
    validation_errors: tuple[str, ...] = (),
) -> tuple[bool, tuple[str, ...]]:
    """Grade exact safety behavior while allowing semantic wording variation."""
    findings: list[str] = []
    if not structurally_valid:
        findings.append(
            "The model response failed structural validation: "
            + ("; ".join(validation_errors) or "unknown validation error")
        )
        return False, tuple(findings)
    if decision != scenario.expected_decision:
        findings.append(f"Expected decision {scenario.expected_decision}, observed {decision}.")
    if len(operations) != len(scenario.expected_operations):
        findings.append(
            f"Expected {len(scenario.expected_operations)} operation(s), observed {len(operations)}."
        )

    remaining = list(operations)
    for expected in scenario.expected_operations:
        match_index = next(
            (
                index
                for index, operation in enumerate(remaining)
                if _operation_matches(expected, operation)
            ),
            None,
        )
        if match_index is None:
            findings.append(_missing_operation_finding(expected))
        else:
            remaining.pop(match_index)

    searchable = " ".join(_operation_search_text(operation) for operation in operations)
    for forbidden in scenario.forbidden_concepts:
        if forbidden.casefold() in searchable:
            findings.append(f"Forbidden assistant-derived concept was stored: {forbidden}.")
    return not findings, tuple(findings or ["Memory behavior matched the expected result."])


def scenario_result_payload(
    result: MemoryScenarioResult,
    *,
    scenario: MemoryShadowScenario,
) -> dict[str, Any]:
    """Create the stable JSON/report record for one scenario."""
    return {
        "scenario_id": scenario.id,
        "description": scenario.description,
        "passed": result.passed,
        "tags": list(scenario.tags),
        "input": {
            "messages": [dict(message) for message in scenario.messages],
            "processed_through_message_index": scenario.processed_through_message_index,
            "existing_memories": [memory.as_context() for memory in scenario.existing_memories],
        },
        "expected": {
            "decision": scenario.expected_decision,
            "operations": [
                {
                    "operation": operation.operation,
                    "data_point_type": operation.data_point_type,
                    "target_memory_id": operation.target_memory_id,
                    "value_concepts": list(operation.value_concepts),
                    "evidence_message_indexes": list(operation.evidence_message_indexes),
                }
                for operation in scenario.expected_operations
            ],
            "forbidden_concepts": list(scenario.forbidden_concepts),
        },
        "observed": {
            "decision": result.decision,
            "operations": list(result.operations),
            "structurally_valid": result.structurally_valid,
            "validation_errors": list(result.validation_errors),
            "duration_seconds": result.duration_seconds,
            "error": result.error,
        },
        "findings": list(result.findings),
        "raw_response": result.raw_response,
    }


def _operation_matches(expected: ExpectedMemoryOperation, actual: dict[str, Any]) -> bool:
    if actual.get("operation") != expected.operation:
        return False
    if expected.data_point_type and actual.get("data_point_type") != expected.data_point_type:
        return False
    if expected.target_memory_id and actual.get("target_memory_id") != expected.target_memory_id:
        return False
    if expected.evidence_message_indexes and tuple(actual.get("evidence_message_indexes") or ()) != (
        expected.evidence_message_indexes
    ):
        return False
    searchable = _operation_search_text(actual)
    return all(concept.casefold() in searchable for concept in expected.value_concepts)


def _operation_search_text(operation: dict[str, Any]) -> str:
    return json.dumps(operation, ensure_ascii=False, sort_keys=True).casefold()


def _missing_operation_finding(expected: ExpectedMemoryOperation) -> str:
    parts = [expected.operation]
    if expected.data_point_type:
        parts.append(expected.data_point_type)
    if expected.target_memory_id:
        parts.append(f"target={expected.target_memory_id}")
    if expected.value_concepts:
        parts.append("concepts=" + ",".join(expected.value_concepts))
    if expected.evidence_message_indexes:
        parts.append(
            "evidence=" + ",".join(str(index) for index in expected.evidence_message_indexes)
        )
    return "Missing expected operation: " + "; ".join(parts) + "."


def _operation_payload(operation: Any) -> dict[str, Any]:
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


__all__ = [
    "MemoryScenarioResult",
    "grade_memory_shadow_result",
    "run_memory_shadow_scenario",
    "scenario_result_payload",
]
