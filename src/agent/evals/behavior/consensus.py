from __future__ import annotations

from agent.evals.behavior.judge import JudgeProtocolError
from agent.evals.behavior.models import (
    BehaviorJudge,
    BehaviorScenario,
    DimensionGrade,
    JudgeResult,
    ObservedTurn,
    ScenarioTurn,
)


class ConservativeConsensusJudge:
    """Combines judges using the lowest supported score for each dimension."""

    def __init__(self, judges: tuple[tuple[str, BehaviorJudge], ...]) -> None:
        if len(judges) < 2:
            raise ValueError("Consensus judging requires at least two judges.")
        names = [name for name, _judge in judges]
        if any(not name.strip() for name in names) or len(names) != len(set(names)):
            raise ValueError("Consensus judge names must be non-empty and unique.")
        self.judges = judges

    async def judge(
        self,
        *,
        scenario: BehaviorScenario,
        turn: ScenarioTurn,
        observed: ObservedTurn,
        transcript: tuple[ObservedTurn, ...],
    ) -> JudgeResult:
        results: list[tuple[str, JudgeResult]] = []
        for name, judge in self.judges:
            result = await judge.judge(
                scenario=scenario,
                turn=turn,
                observed=observed,
                transcript=transcript,
            )
            results.append((name, result))

        required_ids = tuple(dimension.id for dimension in turn.expectation.rubric)
        grades: list[DimensionGrade] = []
        for dimension_id in required_ids:
            candidates = []
            for name, result in results:
                grade = next(
                    (item for item in result.grades if item.dimension_id == dimension_id),
                    None,
                )
                if grade is None:
                    raise JudgeProtocolError(
                        f"Consensus judge '{name}' omitted dimension '{dimension_id}'."
                    )
                candidates.append((name, grade))
            lowest_name, lowest_grade = min(candidates, key=lambda item: item[1].score)
            evidence = "; ".join(
                f"{name}={grade.score}: {grade.reason}" for name, grade in candidates
            )
            grades.append(
                DimensionGrade(
                    dimension_id=dimension_id,
                    score=lowest_grade.score,
                    reason=f"Conservative score from {lowest_name}. {evidence}",
                )
            )
        overall = " | ".join(
            f"{name}: {result.overall_reason}" for name, result in results
        )
        return JudgeResult(grades=tuple(grades), overall_reason=overall)
