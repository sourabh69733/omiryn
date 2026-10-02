"""Known-answer calibration cases for a v3 memory evidence judge."""

from __future__ import annotations

from dataclasses import replace
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
        message="I want a friend who is calm and curious.",
        memory_kind="relationship",
        purposes=("matching",),
        key="past_relationship_pattern",
        value="Usually befriends calm and curious people",
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


def _context_case(*, assistant_claim: bool) -> MemoryJudgeCalibrationCase:
    """Require context resolution without treating assistant suggestions as facts."""
    case = _case(
        case_id=("reject_v3_assistant_context_claim" if assistant_claim
                 else "accept_v3_cross_batch_reference"),
        message=("That is your guess, not my preference." if assistant_claim
                 else "Calm and funny, but not loud."),
        memory_kind="semantic", purposes=("matching",), key="friend_personality",
        value="calm and funny, but not loud", sensitivity="standard",
        supported=not assistant_claim,
        required_issues=("unsupported_inference",) if assistant_claim else (),
    )
    return replace(
        case,
        messages=(
            {"role": "user", "content": "I want a friend who makes difficult days lighter."},
            {"role": "assistant", "content": (
                "You want a calm, funny friend who is not loud." if assistant_claim
                else "What does that look like to you?"
            )},
            *case.messages,
        ),
        operations=({**case.operations[0], "evidence_message_indexes": [2]},),
    )


def _time_case(*, field: str, mode: str) -> MemoryJudgeCalibrationCase:
    """Exercise semantic grounding of each timestamp, not just ISO validity."""
    supported = mode != "invented"
    timestamp = "2026-08-12T09:30:00+05:30"
    statements = {
        "occurred_at": f"I arrived in Pune at {timestamp}.",
        "valid_from": f"My temporary stay in Pune started at {timestamp}.",
        "valid_until": f"My temporary stay in Pune ended at {timestamp}.",
    }
    case = _case(
        case_id=f"{('accept' if supported else 'reject')}_v3_{mode}_{field}",
        message=statements[field] if mode == "explicit" else "I stayed in Pune last month.",
        memory_kind="episodic", purposes=("personalization",), key="stay_in_pune",
        value="Stayed in Pune", sensitivity="standard", supported=supported,
        required_issues=() if supported else ("unsupported_inference",),
    )
    return replace(case, operations=({
        **case.operations[0],
        "occurred_at": None, "valid_from": None, "valid_until": None,
        field: timestamp if mode != "unknown" else None,
    },))


MEMORY_V3_JUDGE_CALIBRATION_CASES += (
    _context_case(assistant_claim=False),
    _context_case(assistant_claim=True),
    *(
        _time_case(field=field, mode=mode)
        for field in ("occurred_at", "valid_from", "valid_until")
        for mode in ("invented", "explicit")
    ),
    _time_case(field="occurred_at", mode="unknown"),
)


__all__ = ["MEMORY_V3_JUDGE_CALIBRATION_CASES"]
