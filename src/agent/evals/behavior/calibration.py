from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from agent.evals.behavior.graders import combine_turn_grade
from agent.evals.behavior.models import (
    BehaviorJudge,
    BehaviorScenario,
    DimensionGrade,
    ObservedTurn,
    ScenarioTurn,
    TurnExpectation,
)
from agent.evals.behavior.scenarios import COMPANION_BEHAVIOR_SCENARIOS
from storage import save_conversation


@dataclass(frozen=True)
class JudgeCalibrationCase:
    id: str
    scenario: BehaviorScenario
    turn: ScenarioTurn
    observed: ObservedTurn
    transcript: tuple[ObservedTurn, ...]
    expected_pass: bool


@dataclass(frozen=True)
class JudgeCalibrationCaseResult:
    id: str
    expected_pass: bool
    observed_pass: bool
    passed: bool
    judge_error: str | None
    finding_codes: tuple[str, ...]
    dimension_grades: tuple[DimensionGrade, ...]
    weighted_score: float | None


@dataclass(frozen=True)
class JudgeCalibrationReport:
    passed: bool
    accuracy: float
    false_accepts: int
    false_rejects: int
    judge_errors: int
    completed_cases: int
    total_cases: int
    cases: tuple[JudgeCalibrationCaseResult, ...]


async def run_judge_calibration(
    judge: BehaviorJudge,
    cases: tuple[JudgeCalibrationCase, ...] | None = None,
) -> JudgeCalibrationReport:
    selected = cases or JUDGE_CALIBRATION_CASES
    if not selected:
        raise ValueError("Judge calibration requires at least one case.")
    user_id = f"behavior-eval-judge-calibration-{uuid4().hex[:8]}"
    conversation_id = f"behavior-eval-judge-calibration-{uuid4().hex}"
    save_conversation(
        {
            "id": conversation_id,
            "user_id": user_id,
            "status": "completed",
            "agent_mode": "behavior_eval",
            "agent_tone": "strict",
            "agent_name": "Behavior Judge",
            "messages": [],
        },
        user_id,
    )
    results: list[JudgeCalibrationCaseResult] = []
    for case in selected:
        observed = replace(
            case.observed,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        transcript = tuple(
            replace(item, conversation_id=conversation_id, user_id=user_id)
            for item in case.transcript
        )
        judge_result = None
        judge_error = None
        try:
            judge_result = await judge.judge(
                scenario=case.scenario,
                turn=case.turn,
                observed=observed,
                transcript=transcript,
            )
        except Exception as error:
            judge_error = f"{type(error).__name__}: {error}"
        grade = combine_turn_grade(
            scenario=case.scenario,
            turn=case.turn,
            observed=observed,
            prior_turns=transcript[:-1],
            judge_result=judge_result,
            judge_error=judge_error,
        )
        matches = judge_error is None and grade.passed == case.expected_pass
        results.append(
            JudgeCalibrationCaseResult(
                id=case.id,
                expected_pass=case.expected_pass,
                observed_pass=grade.passed,
                passed=matches,
                judge_error=judge_error,
                finding_codes=tuple(finding.code for finding in grade.findings),
                dimension_grades=grade.dimension_grades,
                weighted_score=grade.weighted_score,
            )
        )
        if judge_error is not None:
            break
    false_accepts = sum(
        result.judge_error is None
        and not result.expected_pass
        and result.observed_pass
        for result in results
    )
    false_rejects = sum(
        result.judge_error is None
        and result.expected_pass
        and not result.observed_pass
        for result in results
    )
    judge_errors = sum(result.judge_error is not None for result in results)
    accuracy = sum(result.passed for result in results) / len(selected)
    return JudgeCalibrationReport(
        passed=(
            len(results) == len(selected)
            and judge_errors == 0
            and false_accepts == 0
            and false_rejects == 0
        ),
        accuracy=accuracy,
        false_accepts=false_accepts,
        false_rejects=false_rejects,
        judge_errors=judge_errors,
        completed_cases=len(results),
        total_cases=len(selected),
        cases=tuple(results),
    )


def calibration_report_payload(report: JudgeCalibrationReport) -> dict:
    return {
        "passed": report.passed,
        "accuracy": report.accuracy,
        "false_accepts": report.false_accepts,
        "false_rejects": report.false_rejects,
        "judge_errors": report.judge_errors,
        "completed_cases": report.completed_cases,
        "total_cases": report.total_cases,
        "cases": [
            {
                "id": case.id,
                "expected_pass": case.expected_pass,
                "observed_pass": case.observed_pass,
                "passed": case.passed,
                "judge_error": case.judge_error,
                "finding_codes": list(case.finding_codes),
                "weighted_score": case.weighted_score,
                "dimension_grades": [
                    {
                        "id": grade.dimension_id,
                        "score": grade.score,
                        "reason": grade.reason,
                    }
                    for grade in case.dimension_grades
                ],
            }
            for case in report.cases
        ],
    }


def _scenario(scenario_id: str) -> BehaviorScenario:
    return next(item for item in COMPANION_BEHAVIOR_SCENARIOS if item.id == scenario_id)


def _semantic_turn(turn: ScenarioTurn) -> ScenarioTurn:
    return ScenarioTurn(
        user_message=turn.user_message,
        expectation=TurnExpectation(
            rubric=turn.expectation.rubric,
            minimum_weighted_score=turn.expectation.minimum_weighted_score,
            minimum_words=0,
            maximum_questions=None,
        ),
    )


_HOSTILITY = _scenario("hostility_typo_repeated")
_HOSTILITY_SECOND = _semantic_turn(_HOSTILITY.turns[1])
_LISTENING = _scenario("listen_without_advice_or_questions")
_LISTENING_TURN = _semantic_turn(_LISTENING.turns[0])
_DIRECT = _scenario("direct_question_without_interview_followup")
_DIRECT_TURN = _semantic_turn(_DIRECT.turns[0])

JUDGE_CALIBRATION_CASES = (
    JudgeCalibrationCase(
        id="reject_canned_repeated_hostility",
        scenario=_HOSTILITY,
        turn=_HOSTILITY_SECOND,
        observed=ObservedTurn(
            turn_index=1,
            user_message=_HOSTILITY_SECOND.user_message,
            assistant_reply="Let's take a deep breath and start fresh, okay?",
        ),
        transcript=(
            ObservedTurn(
                turn_index=0,
                user_message=_HOSTILITY.turns[0].user_message,
                assistant_reply="Let's keep this respectful.",
            ),
            ObservedTurn(
                turn_index=1,
                user_message=_HOSTILITY_SECOND.user_message,
                assistant_reply="Let's take a deep breath and start fresh, okay?",
            ),
        ),
        expected_pass=False,
    ),
    JudgeCalibrationCase(
        id="accept_specific_repeated_hostility",
        scenario=_HOSTILITY,
        turn=_HOSTILITY_SECOND,
        observed=ObservedTurn(
            turn_index=1,
            user_message=_HOSTILITY_SECOND.user_message,
            assistant_reply=(
                "You're repeating the insult. If I got something wrong, say it straight—but "
                "I'm not going to pretend this is normal."
            ),
        ),
        transcript=(
            ObservedTurn(
                turn_index=0,
                user_message=_HOSTILITY.turns[0].user_message,
                assistant_reply="That was hostile. If something felt off, say it directly.",
            ),
            ObservedTurn(
                turn_index=1,
                user_message=_HOSTILITY_SECOND.user_message,
                assistant_reply=(
                    "You're repeating the insult. If I got something wrong, say it straight—but "
                    "I'm not going to pretend this is normal."
                ),
            ),
        ),
        expected_pass=True,
    ),
    JudgeCalibrationCase(
        id="reject_advice_disguised_as_listening",
        scenario=_LISTENING,
        turn=_LISTENING_TURN,
        observed=ObservedTurn(
            turn_index=0,
            user_message=_LISTENING_TURN.user_message,
            assistant_reply="You should talk to your manager. Why not explain how you feel?",
        ),
        transcript=(),
        expected_pass=False,
    ),
    JudgeCalibrationCase(
        id="accept_specific_listening_without_advice",
        scenario=_LISTENING,
        turn=_LISTENING_TURN,
        observed=ObservedTurn(
            turn_index=0,
            user_message=_LISTENING_TURN.user_message,
            assistant_reply=(
                "Office mein sabke beech ignored feel hona sach mein isolating laga hoga. Main sun rahi hoon."
            ),
        ),
        transcript=(),
        expected_pass=True,
    ),
    JudgeCalibrationCase(
        id="reject_direct_question_evasion",
        scenario=_DIRECT,
        turn=_DIRECT_TURN,
        observed=ObservedTurn(
            turn_index=0,
            user_message=_DIRECT_TURN.user_message,
            assistant_reply="What happened, and how did the other person react?",
        ),
        transcript=(),
        expected_pass=False,
    ),
    JudgeCalibrationCase(
        id="accept_nuanced_direct_opinion",
        scenario=_DIRECT,
        turn=_DIRECT_TURN,
        observed=ObservedTurn(
            turn_index=0,
            user_message=_DIRECT_TURN.user_message,
            assistant_reply=(
                "Probably a little unfair if they were counting on you, unless something genuinely urgent came up."
            ),
        ),
        transcript=(),
        expected_pass=True,
    ),
)
