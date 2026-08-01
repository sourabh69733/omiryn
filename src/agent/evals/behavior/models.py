from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

FindingSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class RubricDimension:
    id: str
    description: str
    weight: float = 1.0
    minimum_score: int = 3

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Rubric dimension id is required.")
        if not self.description.strip():
            raise ValueError(f"Rubric dimension '{self.id}' needs a description.")
        if self.weight <= 0:
            raise ValueError(f"Rubric dimension '{self.id}' weight must be positive.")
        if not 0 <= self.minimum_score <= 4:
            raise ValueError(f"Rubric dimension '{self.id}' minimum_score must be 0-4.")


@dataclass(frozen=True)
class TurnExpectation:
    forbidden_exact: tuple[str, ...] = ()
    forbidden_substrings: tuple[str, ...] = ()
    required_substrings_any: tuple[str, ...] = ()
    forbidden_direct_reasons: tuple[str, ...] = ()
    minimum_words: int = 1
    maximum_words: int | None = None
    maximum_questions: int | None = 1
    forbid_repeating_prior_reply: bool = False
    rubric: tuple[RubricDimension, ...] = ()
    minimum_weighted_score: float = 3.0

    def __post_init__(self) -> None:
        if self.minimum_words < 0:
            raise ValueError("minimum_words cannot be negative.")
        if self.maximum_words is not None and self.maximum_words < self.minimum_words:
            raise ValueError("maximum_words cannot be lower than minimum_words.")
        if self.maximum_questions is not None and self.maximum_questions < 0:
            raise ValueError("maximum_questions cannot be negative.")
        if not 0 <= self.minimum_weighted_score <= 4:
            raise ValueError("minimum_weighted_score must be 0-4.")
        rubric_ids = [dimension.id for dimension in self.rubric]
        if len(rubric_ids) != len(set(rubric_ids)):
            raise ValueError("Rubric dimension ids must be unique within a turn.")


@dataclass(frozen=True)
class ScenarioTurn:
    user_message: str
    expectation: TurnExpectation

    def __post_init__(self) -> None:
        if not self.user_message.strip():
            raise ValueError("Scenario user_message is required.")


@dataclass(frozen=True)
class BehaviorScenario:
    id: str
    description: str
    turns: tuple[ScenarioTurn, ...]
    initial_messages: tuple[dict[str, Any], ...] = ()
    user_profile: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    samples: int = 1
    minimum_sample_pass_rate: float = 1.0
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Scenario id is required.")
        if not self.description.strip():
            raise ValueError(f"Scenario '{self.id}' needs a description.")
        if not self.turns:
            raise ValueError(f"Scenario '{self.id}' needs at least one turn.")
        if self.samples < 1:
            raise ValueError(f"Scenario '{self.id}' samples must be at least 1.")
        if not 0 < self.minimum_sample_pass_rate <= 1:
            raise ValueError(
                f"Scenario '{self.id}' minimum_sample_pass_rate must be greater than 0 and at most 1."
            )
        if self.schema_version != 1:
            raise ValueError(f"Unsupported behavior scenario schema version: {self.schema_version}.")


@dataclass(frozen=True)
class ObservedTurn:
    turn_index: int
    user_message: str
    assistant_reply: str
    assistant_messages: tuple[str, ...] = ()
    trace_steps: tuple[str, ...] = ()
    direct_reply_reason: str | None = None
    context_summary: dict[str, Any] = field(default_factory=dict)
    conversation_id: str | None = None
    user_id: str | None = None


@dataclass(frozen=True)
class GradeFinding:
    code: str
    message: str
    severity: FindingSeverity = "error"
    evidence: str | None = None


@dataclass(frozen=True)
class DimensionGrade:
    dimension_id: str
    score: int
    reason: str

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 4:
            raise ValueError(f"Dimension score for '{self.dimension_id}' must be 0-4.")


@dataclass(frozen=True)
class JudgeResult:
    grades: tuple[DimensionGrade, ...]
    overall_reason: str


@dataclass(frozen=True)
class TurnGrade:
    turn_index: int
    passed: bool
    findings: tuple[GradeFinding, ...]
    dimension_grades: tuple[DimensionGrade, ...] = ()
    weighted_score: float | None = None
    judge_error: str | None = None


@dataclass(frozen=True)
class SampleResult:
    scenario_id: str
    sample_index: int
    passed: bool
    turns: tuple[ObservedTurn, ...]
    grades: tuple[TurnGrade, ...]


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    passed: bool
    sample_pass_rate: float
    required_sample_pass_rate: float
    samples: tuple[SampleResult, ...]


@dataclass(frozen=True)
class BehaviorEvalReport:
    suite_name: str
    passed: bool
    scenario_passed: int
    scenario_failed: int
    scenarios: tuple[ScenarioResult, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class BehaviorJudge(Protocol):
    async def judge(
        self,
        *,
        scenario: BehaviorScenario,
        turn: ScenarioTurn,
        observed: ObservedTurn,
        transcript: tuple[ObservedTurn, ...],
    ) -> JudgeResult:
        ...


class ScenarioDriver(Protocol):
    async def run_sample(
        self,
        scenario: BehaviorScenario,
        sample_index: int,
    ) -> tuple[ObservedTurn, ...]:
        ...
