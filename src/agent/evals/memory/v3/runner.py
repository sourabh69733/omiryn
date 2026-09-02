"""Runs canonical-memory scenarios through the real v3 cognition contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from agent.cognition.background.coordination import interpret_background_cognition
from agent.cognition.background.prompt import background_cognition_prompt
from agent.evals.behavior.core.events import EventSink, emit_event
from agent.evals.memory.judge import MemoryEvidenceJudge, memory_evidence_judgment_payload
from agent.memory_engine.memories.operations import (
    MemoryAddProposal,
    MemoryReinforceProposal,
    MemoryRetractProposal,
    MemorySupersedeProposal,
)
from agent.memory_engine.processing import MemoryProcessingState, build_memory_batch
from agent.providers import analyze_background_cognition
from storage import save_conversation

from .scenarios import ExpectedMemoryV3Operation, MemoryV3Scenario


@dataclass(frozen=True)
class MemoryV3ScenarioResult:
    """Expected-versus-observed result for one v3 cognition batch."""

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
    semantic_judgment: dict[str, Any] | None = None
    semantic_judge_error: str | None = None


async def run_memory_v3_scenario(
    *,
    scenario: MemoryV3Scenario,
    model: str | None,
    timeout_seconds: float,
    event_sink: EventSink | None = None,
    semantic_judge: MemoryEvidenceJudge | None = None,
) -> MemoryV3ScenarioResult:
    """Call cognition once with memory_version=3 and grade without persisting proposals."""
    conversation_id = f"memory-v3-eval-{scenario.id}-{uuid4().hex}"
    user_id = f"memory-v3-eval-user-{scenario.id}"
    has_state = scenario.processed_through_message_index >= 0 or any(
        (
            scenario.previous_handoff.summary,
            scenario.previous_handoff.active_people,
            scenario.previous_handoff.active_topics,
            scenario.previous_handoff.unresolved_references,
        )
    )
    state = (
        MemoryProcessingState(
            conversation_id=conversation_id,
            user_id=user_id,
            processed_through_message_index=scenario.processed_through_message_index,
            handoff=scenario.previous_handoff,
        )
        if has_state
        else None
    )
    batch = build_memory_batch(
        conversation_id=conversation_id,
        user_id=user_id,
        messages=[dict(message) for message in scenario.messages],
        state=state,
    )
    if batch is None:
        return _error_result(scenario.id, "Scenario produced no pending batch.", 0)

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
        "V3 memory scenario started.",
        scenario_id=scenario.id,
        expected_decision=scenario.expected_decision,
    )
    emit_event(
        event_sink,
        "memory_call_started",
        "V3 cognition call started.",
        scenario_id=scenario.id,
        model_name=model or "provider-default",
    )
    started = perf_counter()
    try:
        raw = await analyze_background_cognition(
            background_cognition_prompt(batch, existing_memories, []),
            conversation_id=conversation_id,
            model=model,
            timeout_seconds=timeout_seconds,
            memory_version=3,
        )
    except Exception as error:
        duration = round(perf_counter() - started, 3)
        message = f"{type(error).__name__}: {error}"
        emit_event(
            event_sink,
            "memory_call_failed",
            "V3 cognition call failed.",
            scenario_id=scenario.id,
            error=message,
            duration_seconds=duration,
        )
        return _error_result(scenario.id, message, duration)
    duration = round(perf_counter() - started, 3)
    emit_event(
        event_sink,
        "memory_call_completed",
        "V3 cognition call completed.",
        scenario_id=scenario.id,
        duration_seconds=duration,
    )

    cognition = interpret_background_cognition(
        raw,
        batch=batch,
        existing_memory_ids={memory.id for memory in scenario.existing_memories},
        thread_candidates=[],
        memory_version=3,
    )
    analysis = cognition.memory
    operations = tuple(_operation_payload(operation) for operation in analysis.operations)
    passed, findings = grade_memory_v3_result(
        scenario=scenario,
        decision=analysis.decision,
        operations=operations,
        structurally_valid=analysis.valid,
        validation_errors=analysis.errors,
    )
    semantic_judgment = None
    semantic_judge_error = None
    if semantic_judge is not None and analysis.valid and operations:
        try:
            judgment = await semantic_judge.judge_memories(
                messages=scenario.messages,
                operations=operations,
                conversation_id=conversation_id,
            )
        except Exception as error:
            semantic_judge_error = f"{type(error).__name__}: {error}"
            findings = (*findings, f"Semantic evidence judge error: {semantic_judge_error}")
            passed = False
        else:
            semantic_judgment = memory_evidence_judgment_payload(
                judgment, judge_name=semantic_judge.judge_name
            )
            if not judgment.passed:
                findings = (
                    *findings,
                    *(
                        f"Semantic evidence issue for operation {item.index}: {', '.join(item.issues)} — {item.reason}"
                        for item in judgment.operations
                        if not item.supported
                    ),
                )
                passed = False
    emit_event(
        event_sink,
        "memory_scenario_completed",
        "V3 memory scenario completed.",
        scenario_id=scenario.id,
        passed=passed,
        operation_count=len(operations),
        findings=list(findings),
    )
    return MemoryV3ScenarioResult(
        scenario_id=scenario.id,
        passed=passed,
        decision=analysis.decision,
        operations=operations,
        structurally_valid=analysis.valid,
        validation_errors=analysis.errors,
        findings=findings,
        raw_response=raw,
        duration_seconds=duration,
        semantic_judgment=semantic_judgment,
        semantic_judge_error=semantic_judge_error,
    )


def grade_memory_v3_result(
    *,
    scenario: MemoryV3Scenario,
    decision: str,
    operations: tuple[dict[str, Any], ...],
    structurally_valid: bool,
    validation_errors: tuple[str, ...] = (),
) -> tuple[bool, tuple[str, ...]]:
    """Grade core meaning strictly while tolerating labels and phrasing."""
    if not structurally_valid:
        return False, (
            "The model response failed structural validation: "
            + ("; ".join(validation_errors) or "unknown validation error"),
        )
    findings: list[str] = []
    if decision != scenario.expected_decision:
        findings.append(f"Expected decision {scenario.expected_decision}, observed {decision}.")
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
    optional = list(scenario.optional_operations)
    unmatched: list[dict[str, Any]] = []
    for operation in remaining:
        match_index = next(
            (
                index
                for index, expected in enumerate(optional)
                if _operation_matches(expected, operation)
            ),
            None,
        )
        if match_index is None:
            unmatched.append(operation)
        else:
            optional.pop(match_index)
    if not scenario.allow_additional_operations:
        for operation in unmatched:
            findings.append(
                f"Unexpected operation: {operation.get('operation')} / {operation.get('memory_kind') or 'existing memory'} / {operation.get('key') or 'unlabelled'}."
            )
    searchable = " ".join(_operation_search_text(operation) for operation in operations)
    for forbidden in scenario.forbidden_concepts:
        if forbidden.casefold() in searchable:
            findings.append(f"Forbidden assistant-derived concept was stored: {forbidden}.")
    return not findings, tuple(findings or ["V3 memory behavior matched the expected result."])


def scenario_result_payload(
    result: MemoryV3ScenarioResult, *, scenario: MemoryV3Scenario
) -> dict[str, Any]:
    """Serialize one V3 result for JSON, Markdown, and history reports."""

    def serialize_expected(item: ExpectedMemoryV3Operation) -> dict[str, Any]:
        return {
            "operation": item.operation,
            "memory_kind": item.memory_kind,
            "required_purposes": list(item.required_purposes),
            "forbidden_purposes": list(item.forbidden_purposes),
            "target_memory_id": item.target_memory_id,
            "value_concepts": list(item.value_concepts),
            "evidence_message_indexes": list(item.evidence_message_indexes),
            "sensitivity": item.sensitivity,
        }

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
            "operations": [serialize_expected(item) for item in scenario.expected_operations],
            "optional_operations": [
                serialize_expected(item) for item in scenario.optional_operations
            ],
            "forbidden_concepts": list(scenario.forbidden_concepts),
            "allow_additional_operations": scenario.allow_additional_operations,
        },
        "observed": {
            "decision": result.decision,
            "operations": list(result.operations),
            "structurally_valid": result.structurally_valid,
            "validation_errors": list(result.validation_errors),
            "duration_seconds": result.duration_seconds,
            "error": result.error,
            "semantic_judgment": result.semantic_judgment,
            "semantic_judge_error": result.semantic_judge_error,
        },
        "findings": list(result.findings),
        "raw_response": result.raw_response,
    }


def _operation_matches(expected: ExpectedMemoryV3Operation, actual: dict[str, Any]) -> bool:
    if actual.get("operation") != expected.operation:
        return False
    if expected.memory_kind and actual.get("memory_kind") != expected.memory_kind:
        return False
    purposes = set(actual.get("purposes") or [])
    if expected.required_purposes and purposes != set(expected.required_purposes):
        return False
    if set(expected.forbidden_purposes).intersection(purposes):
        return False
    if expected.target_memory_id and actual.get("target_memory_id") != expected.target_memory_id:
        return False
    if (
        expected.evidence_message_indexes
        and tuple(actual.get("evidence_message_indexes") or ()) != expected.evidence_message_indexes
    ):
        return False
    if expected.sensitivity and actual.get("sensitivity") != expected.sensitivity:
        return False
    searchable = _operation_search_text(actual)
    return all(concept.casefold() in searchable for concept in expected.value_concepts)


def _operation_search_text(operation: dict[str, Any]) -> str:
    return json.dumps(operation, ensure_ascii=False, sort_keys=True).casefold()


def _missing_operation_finding(expected: ExpectedMemoryV3Operation) -> str:
    parts = [expected.operation]
    if expected.memory_kind:
        parts.append(expected.memory_kind)
    if expected.required_purposes:
        parts.append("purposes=" + ",".join(expected.required_purposes))
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
    if isinstance(operation, MemorySupersedeProposal):
        payload = _add_payload(operation.replacement)
        payload.update(operation="supersede", target_memory_id=operation.target_memory_id)
        return payload
    if isinstance(operation, MemoryAddProposal):
        return {"operation": "add", "target_memory_id": None, **_add_payload(operation)}
    if isinstance(operation, MemoryReinforceProposal):
        return {
            "operation": "reinforce",
            "target_memory_id": operation.target_memory_id,
            "confidence": operation.confidence,
            "importance": operation.importance,
            "evidence_message_indexes": list(operation.evidence_message_indexes),
        }
    if isinstance(operation, MemoryRetractProposal):
        return {
            "operation": "retract",
            "target_memory_id": operation.target_memory_id,
            "evidence_message_indexes": list(operation.evidence_message_indexes),
        }
    raise TypeError(f"Unsupported V3 memory operation: {type(operation).__name__}")


def _add_payload(operation: MemoryAddProposal) -> dict[str, Any]:
    return {
        "memory_kind": operation.kind.value,
        "purposes": sorted(purpose.value for purpose in operation.purposes),
        "key": operation.key,
        "value": operation.value,
        "sensitivity": operation.sensitivity.value,
        "confidence": operation.confidence,
        "importance": operation.importance,
        "occurred_at": operation.occurred_at.isoformat() if operation.occurred_at else None,
        "valid_from": operation.valid_from.isoformat() if operation.valid_from else None,
        "valid_until": operation.valid_until.isoformat() if operation.valid_until else None,
        "evidence_message_indexes": list(operation.evidence_message_indexes),
    }


def _error_result(scenario_id: str, message: str, duration: float) -> MemoryV3ScenarioResult:
    return MemoryV3ScenarioResult(
        scenario_id=scenario_id,
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


__all__ = [
    "MemoryV3ScenarioResult",
    "grade_memory_v3_result",
    "run_memory_v3_scenario",
    "scenario_result_payload",
]
