"""Calibrates the semantic memory judge against known evidence decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent.evals.behavior.core.events import EventSink, emit_event
from storage import save_conversation

from .judge import MemoryEvidenceJudge, MemoryOperationJudgment


@dataclass(frozen=True)
class MemoryJudgeExpectedVerdict:
    """Known semantic result for one proposed operation."""

    supported: bool
    required_issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.supported and self.required_issues:
            raise ValueError("A supported calibration verdict cannot require issues.")
        if not self.supported and not self.required_issues:
            raise ValueError("A rejected calibration verdict requires an issue category.")


@dataclass(frozen=True)
class MemoryJudgeCalibrationCase:
    """Synthetic evidence, proposal, and known result used to test a judge."""

    id: str
    messages: tuple[dict[str, Any], ...]
    operations: tuple[dict[str, Any], ...]
    expected_verdicts: tuple[MemoryJudgeExpectedVerdict, ...]

    def __post_init__(self) -> None:
        if not self.operations:
            raise ValueError("A memory judge calibration case requires an operation.")
        if len(self.operations) != len(self.expected_verdicts):
            raise ValueError("Every calibration operation requires one expected verdict.")


@dataclass(frozen=True)
class MemoryJudgeCalibrationOperationResult:
    """Comparison between one known verdict and the judge response."""

    index: int
    expected_supported: bool
    observed_supported: bool
    required_issues: tuple[str, ...]
    observed_issues: tuple[str, ...]
    passed: bool
    reason: str
    failure_reason: str | None


@dataclass(frozen=True)
class MemoryJudgeCalibrationCaseResult:
    """Calibration outcome for one synthetic evidence case."""

    id: str
    passed: bool
    evidence_messages: tuple[str, ...]
    proposed_operations: tuple[dict[str, Any], ...]
    judge_error: str | None
    failure_reason: str | None
    operations: tuple[MemoryJudgeCalibrationOperationResult, ...]


@dataclass(frozen=True)
class MemoryJudgeCalibrationReport:
    """Fail-closed reliability report for a semantic memory judge."""

    passed: bool
    accuracy: float
    false_accepts: int
    false_rejects: int
    issue_mismatches: int
    judge_errors: int
    completed_cases: int
    total_cases: int
    cases: tuple[MemoryJudgeCalibrationCaseResult, ...]


async def run_memory_judge_calibration(
    judge: MemoryEvidenceJudge,
    *,
    cases: tuple[MemoryJudgeCalibrationCase, ...] | None = None,
    event_sink: EventSink | None = None,
) -> MemoryJudgeCalibrationReport:
    """Run known examples before trusting a judge on extracted memories."""
    selected = cases or MEMORY_JUDGE_CALIBRATION_CASES
    if not selected:
        raise ValueError("Memory judge calibration requires at least one case.")
    emit_event(
        event_sink,
        "memory_judge_calibration_started",
        "Memory judge calibration started.",
        total_cases=len(selected),
    )
    user_id = f"memory-judge-calibration-{uuid4().hex[:8]}"
    conversation_id = f"memory-judge-calibration-{uuid4().hex}"
    save_conversation(
        {
            "id": conversation_id,
            "user_id": user_id,
            "status": "completed",
            "agent_mode": "memory_eval",
            "agent_name": "Memory Evidence Judge",
            "messages": [],
        },
        user_id,
    )

    results: list[MemoryJudgeCalibrationCaseResult] = []
    for case_number, case in enumerate(selected, start=1):
        emit_event(
            event_sink,
            "memory_judge_calibration_case_started",
            "Memory judge calibration case started.",
            case_id=case.id,
            case_number=case_number,
            total_cases=len(selected),
            evidence_messages=[
                str(message.get("content") or "")
                for message in case.messages
                if message.get("role") == "user"
            ],
            operations=[dict(operation) for operation in case.operations],
        )
        judge_error = None
        operation_results: tuple[MemoryJudgeCalibrationOperationResult, ...] = ()
        try:
            judgment = await judge.judge_memories(
                messages=case.messages,
                operations=case.operations,
                conversation_id=conversation_id,
            )
            operation_results = tuple(
                _grade_operation(expected, observed)
                for expected, observed in zip(
                    case.expected_verdicts,
                    judgment.operations,
                    strict=True,
                )
            )
        except Exception as error:
            judge_error = f"{type(error).__name__}: {error}"
        case_passed = judge_error is None and all(result.passed for result in operation_results)
        failure_reason = _case_failure_reason(
            judge_error=judge_error,
            operations=operation_results,
        )
        results.append(
            MemoryJudgeCalibrationCaseResult(
                id=case.id,
                passed=case_passed,
                evidence_messages=tuple(
                    str(message.get("content") or "")
                    for message in case.messages
                    if message.get("role") == "user"
                ),
                proposed_operations=tuple(dict(operation) for operation in case.operations),
                judge_error=judge_error,
                failure_reason=failure_reason,
                operations=operation_results,
            )
        )
        emit_event(
            event_sink,
            "memory_judge_calibration_case_completed",
            "Memory judge calibration case completed.",
            case_id=case.id,
            case_number=case_number,
            passed=case_passed,
            judge_error=judge_error,
            failure_reason=failure_reason,
            expected_verdicts=[
                {
                    "supported": verdict.supported,
                    "required_issues": list(verdict.required_issues),
                }
                for verdict in case.expected_verdicts
            ],
            observed_verdicts=[
                {
                    "supported": verdict.observed_supported,
                    "issues": list(verdict.observed_issues),
                    "reason": verdict.reason,
                }
                for verdict in operation_results
            ],
        )
        if judge_error is not None:
            break

    operation_results = [operation for result in results for operation in result.operations]
    false_accepts = sum(
        not result.expected_supported and result.observed_supported for result in operation_results
    )
    false_rejects = sum(
        result.expected_supported and not result.observed_supported for result in operation_results
    )
    issue_mismatches = sum(
        not result.expected_supported
        and not result.observed_supported
        and not set(result.required_issues).issubset(result.observed_issues)
        for result in operation_results
    )
    judge_errors = sum(result.judge_error is not None for result in results)
    report = MemoryJudgeCalibrationReport(
        passed=(
            len(results) == len(selected)
            and judge_errors == 0
            and all(result.passed for result in results)
        ),
        accuracy=sum(result.passed for result in results) / len(selected),
        false_accepts=false_accepts,
        false_rejects=false_rejects,
        issue_mismatches=issue_mismatches,
        judge_errors=judge_errors,
        completed_cases=len(results),
        total_cases=len(selected),
        cases=tuple(results),
    )
    emit_event(
        event_sink,
        "memory_judge_calibration_completed",
        "Memory judge calibration completed.",
        passed=report.passed,
        completed_cases=report.completed_cases,
        total_cases=report.total_cases,
        judge_errors=report.judge_errors,
    )
    return report


def _grade_operation(
    expected: MemoryJudgeExpectedVerdict,
    observed: MemoryOperationJudgment,
) -> MemoryJudgeCalibrationOperationResult:
    support_matches = observed.supported == expected.supported
    issues_match = expected.supported or set(expected.required_issues).issubset(observed.issues)
    failure_reason = None
    if not support_matches:
        failure_reason = (
            "The judge accepted an operation that should be rejected."
            if observed.supported
            else "The judge rejected an operation that should be accepted."
        )
    elif not issues_match:
        missing = sorted(set(expected.required_issues) - set(observed.issues))
        failure_reason = "Missing required issue category: " + ", ".join(missing) + "."
    return MemoryJudgeCalibrationOperationResult(
        index=observed.index,
        expected_supported=expected.supported,
        observed_supported=observed.supported,
        required_issues=expected.required_issues,
        observed_issues=observed.issues,
        passed=support_matches and issues_match,
        reason=observed.reason,
        failure_reason=failure_reason,
    )


def _case_failure_reason(
    *,
    judge_error: str | None,
    operations: tuple[MemoryJudgeCalibrationOperationResult, ...],
) -> str | None:
    if judge_error is not None:
        return judge_error
    failures = [item.failure_reason for item in operations if item.failure_reason]
    return " ".join(failures) or None


def calibration_report_payload(report: MemoryJudgeCalibrationReport) -> dict[str, Any]:
    """Serialize a calibration report for JSON and readable report writers."""
    return {
        "passed": report.passed,
        "accuracy": report.accuracy,
        "false_accepts": report.false_accepts,
        "false_rejects": report.false_rejects,
        "issue_mismatches": report.issue_mismatches,
        "judge_errors": report.judge_errors,
        "completed_cases": report.completed_cases,
        "total_cases": report.total_cases,
        "cases": [
            {
                "id": case.id,
                "passed": case.passed,
                "evidence_messages": list(case.evidence_messages),
                "proposed_operations": list(case.proposed_operations),
                "judge_error": case.judge_error,
                "failure_reason": case.failure_reason,
                "operations": [
                    {
                        "index": operation.index,
                        "expected_supported": operation.expected_supported,
                        "observed_supported": operation.observed_supported,
                        "required_issues": list(operation.required_issues),
                        "observed_issues": list(operation.observed_issues),
                        "passed": operation.passed,
                        "reason": operation.reason,
                        "failure_reason": operation.failure_reason,
                    }
                    for operation in case.operations
                ],
            }
            for case in report.cases
        ],
    }


def _case(
    *,
    case_id: str,
    message: str,
    data_point_type: str,
    memory_basis: str,
    category: str,
    key: str,
    label: str,
    value: Any,
    supported: bool,
    required_issues: tuple[str, ...] = (),
) -> MemoryJudgeCalibrationCase:
    return MemoryJudgeCalibrationCase(
        id=case_id,
        messages=({"role": "user", "content": message},),
        operations=(
            {
                "operation": "add",
                "target_memory_id": None,
                "data_point_type": data_point_type,
                "memory_basis": memory_basis,
                "category": category,
                "key": key,
                "label": label,
                "value": value,
                "confidence": 0.9,
                "evidence_message_indexes": [0],
            },
        ),
        expected_verdicts=(
            MemoryJudgeExpectedVerdict(
                supported=supported,
                required_issues=required_issues,
            ),
        ),
    )


MEMORY_JUDGE_CALIBRATION_CASES = (
    _case(
        case_id="accept_explicit_profile_fact",
        message="I work as a civil engineer.",
        data_point_type="profile_fact",
        memory_basis="stable_user_attribute",
        category="work",
        key="occupation",
        label="Works as a civil engineer",
        value="civil engineer",
        supported=True,
    ),
    _case(
        case_id="accept_explicit_matching_preference",
        message="I want a partner who is calm and curious.",
        data_point_type="matching_fact",
        memory_basis="explicit_matching_preference",
        category="partner_personality",
        key="preferred_partner_traits",
        label="Prefers a calm and curious partner",
        value=["calm", "curious"],
        supported=True,
    ),
    _case(
        case_id="accept_direct_chat_preference",
        message="Please ask me fewer questions and share your own thoughts too.",
        data_point_type="chat_learning",
        memory_basis="direct_chat_preference",
        category="conversation_style",
        key="question_frequency",
        label="Prefers fewer questions and more reciprocal conversation",
        value={"questions": "fewer", "reciprocity": "more"},
        supported=True,
    ),
    _case(
        case_id="reject_invented_identity",
        message="I am building a matchmaking product.",
        data_point_type="profile_fact",
        memory_basis="stable_user_attribute",
        category="work",
        key="job_title",
        label="Works as a professional matchmaker",
        value="professional matchmaker",
        supported=False,
        required_issues=("unsupported_inference",),
    ),
    _case(
        case_id="reject_wrong_memory_type",
        message="I live in Pune.",
        data_point_type="matching_fact",
        memory_basis="explicit_matching_preference",
        category="location",
        key="preferred_partner_location",
        label="Prefers a partner from Pune",
        value="Pune",
        supported=False,
        required_issues=("wrong_memory_type",),
    ),
    _case(
        case_id="reject_incidental_subject",
        message="Can you explain how Python decorators work?",
        data_point_type="profile_fact",
        memory_basis="stable_user_attribute",
        category="interests",
        key="favorite_programming_language",
        label="Likes Python",
        value="Python",
        supported=False,
        required_issues=("incidental_content",),
    ),
    _case(
        case_id="reject_distorted_frequency",
        message="I cook sometimes when I have time.",
        data_point_type="profile_fact",
        memory_basis="stable_user_attribute",
        category="lifestyle",
        key="cooking_habit",
        label="Cooks every day",
        value="daily",
        supported=False,
        required_issues=("distorted_meaning",),
    ),
    _case(
        case_id="reject_over_broad_preference",
        message="I usually get along well with calm people.",
        data_point_type="matching_fact",
        memory_basis="explicit_matching_preference",
        category="partner_personality",
        key="required_partner_personality",
        label="Will only date quiet introverts",
        value={"required": ["quiet", "introverted"]},
        supported=False,
        required_issues=("over_broad",),
    ),
)


__all__ = [
    "MEMORY_JUDGE_CALIBRATION_CASES",
    "MemoryJudgeCalibrationCase",
    "MemoryJudgeCalibrationReport",
    "MemoryJudgeExpectedVerdict",
    "calibration_report_payload",
    "run_memory_judge_calibration",
]
