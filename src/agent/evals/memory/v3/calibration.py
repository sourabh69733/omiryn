"""Known-answer calibration cases for a v3 memory evidence judge."""

from __future__ import annotations

from typing import Any

from agent.evals.memory.calibration import (
    MemoryJudgeCalibrationCase,
    MemoryJudgeExpectedVerdict,
)


def _case(
    *,
    case_id: str,
    message: str,
    memory_kind: str,
    purposes: tuple[str, ...],
    key: str,
    value: Any,
    sensitivity: str,
    supported: bool,
    required_issues: tuple[str, ...] = (),
) -> MemoryJudgeCalibrationCase:
    return MemoryJudgeCalibrationCase(
        id=case_id,
        messages=({"role": "user", "content": message},),
        operations=(
            {
                "operation": "add",
                "memory_kind": memory_kind,
                "purposes": list(purposes),
                "key": key,
                "value": value,
                "sensitivity": sensitivity,
                "confidence": 0.9,
                "importance": 0.7,
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


MEMORY_V3_JUDGE_CALIBRATION_CASES = (
    _case(
        case_id="accept_v3_semantic_profile",
        message="I work as a civil engineer.",
        memory_kind="semantic",
        purposes=("profile",),
        key="occupation",
        value="civil engineer",
        sensitivity="standard",
        supported=True,
    ),
    _case(
        case_id="accept_v3_relationship_personalization",
        message="My ex and I avoided difficult conversations until they became arguments.",
        memory_kind="relationship",
        purposes=("personalization",),
        key="past_relationship_conflict_pattern",
        value="Avoided difficult conversations until arguments developed",
        sensitivity="sensitive",
        supported=True,
    ),
    _case(
        case_id="accept_v3_procedural_preference",
        message="Please ask me fewer questions and share your own thoughts too.",
        memory_kind="procedural",
        purposes=("personalization",),
        key="conversation_reciprocity",
        value={"questions": "fewer", "companion_thoughts": "more"},
        sensitivity="standard",
        supported=True,
    ),
    _case(
        case_id="reject_v3_invented_identity",
        message="I am building a matchmaking product.",
        memory_kind="semantic",
        purposes=("profile",),
        key="job_title",
        value="professional matchmaker",
        sensitivity="standard",
        supported=False,
        required_issues=("unsupported_inference",),
    ),
    _case(
        case_id="reject_v3_wrong_relationship_kind",
        message="I want a partner who is calm and curious.",
        memory_kind="relationship",
        purposes=("matching",),
        key="past_relationship_pattern",
        value="Usually dates calm and curious people",
        sensitivity="sensitive",
        supported=False,
        required_issues=("wrong_memory_type",),
    ),
    _case(
        case_id="reject_v3_incidental_subject",
        message="Can you explain how Python decorators work?",
        memory_kind="semantic",
        purposes=("profile",),
        key="favorite_programming_language",
        value="Python",
        sensitivity="standard",
        supported=False,
        required_issues=("incidental_content",),
    ),
    _case(
        case_id="reject_v3_distorted_frequency",
        message="I cook sometimes when I have time.",
        memory_kind="semantic",
        purposes=("profile",),
        key="cooking_habit",
        value="Cooks every day",
        sensitivity="standard",
        supported=False,
        required_issues=("distorted_meaning",),
    ),
    _case(
        case_id="reject_v3_underclassified_medical_sensitivity",
        message="I have a severe peanut allergy.",
        memory_kind="semantic",
        purposes=("profile",),
        key="peanut_allergy",
        value="severe",
        sensitivity="standard",
        supported=False,
        required_issues=("wrong_sensitivity",),
    ),
)


__all__ = ["MEMORY_V3_JUDGE_CALIBRATION_CASES"]
