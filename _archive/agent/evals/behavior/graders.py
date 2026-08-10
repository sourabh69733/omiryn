from __future__ import annotations

import re

from agent.context_engine.utils import normalized_memory_text
from agent.evals.behavior.models import (
    BehaviorScenario,
    GradeFinding,
    JudgeResult,
    ObservedTurn,
    ScenarioTurn,
    TurnGrade,
)

QUESTION_MARKS = {"?", "؟", "？"}


def hard_rule_findings(
    turn: ScenarioTurn,
    observed: ObservedTurn,
    prior_turns: tuple[ObservedTurn, ...],
) -> tuple[GradeFinding, ...]:
    expectation = turn.expectation
    reply = observed.assistant_reply.strip()
    canonical_reply = _canonical(reply)
    canonical_exact_reply = _canonical_exact(reply)
    findings: list[GradeFinding] = []

    if not reply:
        findings.append(
            GradeFinding(
                code="empty_reply",
                message="Assistant produced no usable reply.",
            )
        )
        return tuple(findings)

    forbidden_exact = {_canonical_exact(value) for value in expectation.forbidden_exact}
    if canonical_exact_reply in forbidden_exact:
        findings.append(
            GradeFinding(
                code="forbidden_exact_reply",
                message="Reply matched a forbidden dismissive or unsafe response.",
                evidence=reply,
            )
        )

    for forbidden in expectation.forbidden_substrings:
        canonical_forbidden = _canonical(forbidden)
        if canonical_forbidden and canonical_forbidden in canonical_reply:
            findings.append(
                GradeFinding(
                    code="forbidden_reply_content",
                    message=f"Reply contained forbidden content: {forbidden!r}.",
                    evidence=reply,
                )
            )

    if expectation.required_substrings_any:
        required = tuple(_canonical(value) for value in expectation.required_substrings_any)
        if not any(value and value in canonical_reply for value in required):
            findings.append(
                GradeFinding(
                    code="missing_required_content",
                    message=(
                        "Reply did not contain any required content option: "
                        f"{list(expectation.required_substrings_any)}."
                    ),
                    evidence=reply,
                )
            )

    word_count = len(re.findall(r"\b[\w']+\b", reply, flags=re.UNICODE))
    if word_count < expectation.minimum_words:
        findings.append(
            GradeFinding(
                code="reply_too_short",
                message=(
                    f"Reply had {word_count} words; minimum is {expectation.minimum_words}."
                ),
                evidence=reply,
            )
        )
    if expectation.maximum_words is not None and word_count > expectation.maximum_words:
        findings.append(
            GradeFinding(
                code="reply_too_long",
                message=(
                    f"Reply had {word_count} words; maximum is {expectation.maximum_words}."
                ),
                evidence=reply,
            )
        )

    question_count = sum(character in QUESTION_MARKS for character in reply)
    if (
        expectation.maximum_questions is not None
        and question_count > expectation.maximum_questions
    ):
        findings.append(
            GradeFinding(
                code="too_many_questions",
                message=(
                    f"Reply used {question_count} questions; maximum is "
                    f"{expectation.maximum_questions}."
                ),
                evidence=reply,
            )
        )

    if (
        observed.direct_reply_reason
        and observed.direct_reply_reason in expectation.forbidden_direct_reasons
    ):
        findings.append(
            GradeFinding(
                code="forbidden_direct_reply_path",
                message=(
                    "Turn was incorrectly short-circuited by direct reply reason "
                    f"{observed.direct_reply_reason!r}."
                ),
                evidence=observed.direct_reply_reason,
            )
        )

    if expectation.forbid_repeating_prior_reply and any(
        _canonical_exact(prior.assistant_reply) == canonical_exact_reply
        for prior in prior_turns
        if prior.assistant_reply.strip()
    ):
        findings.append(
            GradeFinding(
                code="repeated_assistant_reply",
                message="Assistant repeated an earlier reply despite changed conversation state.",
                evidence=reply,
            )
        )

    return tuple(findings)


def combine_turn_grade(
    *,
    scenario: BehaviorScenario,
    turn: ScenarioTurn,
    observed: ObservedTurn,
    prior_turns: tuple[ObservedTurn, ...],
    judge_result: JudgeResult | None,
    judge_error: str | None,
) -> TurnGrade:
    findings = list(hard_rule_findings(turn, observed, prior_turns))
    weighted_score: float | None = None
    dimension_grades = judge_result.grades if judge_result else ()

    if turn.expectation.rubric:
        if judge_error:
            findings.append(
                GradeFinding(
                    code="judge_error",
                    message="Semantic judge failed; rubric-bearing turn fails closed.",
                    evidence=judge_error,
                )
            )
        elif not judge_result:
            findings.append(
                GradeFinding(
                    code="missing_semantic_judgment",
                    message="Semantic rubric was configured but no judge result was provided.",
                )
            )
        else:
            expected_dimensions = {
                dimension.id: dimension for dimension in turn.expectation.rubric
            }
            observed_dimensions = {grade.dimension_id: grade for grade in judge_result.grades}
            missing = sorted(set(expected_dimensions) - set(observed_dimensions))
            unexpected = sorted(set(observed_dimensions) - set(expected_dimensions))
            if missing:
                findings.append(
                    GradeFinding(
                        code="missing_rubric_dimensions",
                        message=f"Judge omitted rubric dimensions: {missing}.",
                    )
                )
            if unexpected:
                findings.append(
                    GradeFinding(
                        code="unexpected_rubric_dimensions",
                        message=f"Judge returned unknown rubric dimensions: {unexpected}.",
                    )
                )
            for dimension_id, dimension in expected_dimensions.items():
                grade = observed_dimensions.get(dimension_id)
                if grade and grade.score < dimension.minimum_score:
                    findings.append(
                        GradeFinding(
                            code="rubric_dimension_below_threshold",
                            message=(
                                f"Dimension '{dimension_id}' scored {grade.score}; minimum is "
                                f"{dimension.minimum_score}."
                            ),
                            evidence=grade.reason,
                        )
                    )
            if not missing and not unexpected:
                total_weight = sum(
                    dimension.weight for dimension in expected_dimensions.values()
                )
                weighted_score = sum(
                    observed_dimensions[dimension_id].score * dimension.weight
                    for dimension_id, dimension in expected_dimensions.items()
                ) / total_weight
                if weighted_score < turn.expectation.minimum_weighted_score:
                    findings.append(
                        GradeFinding(
                            code="weighted_rubric_score_below_threshold",
                            message=(
                                f"Weighted rubric score was {weighted_score:.2f}; minimum is "
                                f"{turn.expectation.minimum_weighted_score:.2f}."
                            ),
                            evidence=judge_result.overall_reason,
                        )
                    )

    return TurnGrade(
        turn_index=observed.turn_index,
        passed=not any(finding.severity == "error" for finding in findings),
        findings=tuple(findings),
        dimension_grades=dimension_grades,
        weighted_score=weighted_score,
        judge_error=judge_error,
    )


def _canonical(text: str) -> str:
    return normalized_memory_text(text).casefold()


def _canonical_exact(text: str) -> str:
    return _canonical(text).replace(" ", "")
