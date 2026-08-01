from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.evals.behavior.graders import combine_turn_grade
from agent.evals.behavior.models import (
    BehaviorEvalReport,
    BehaviorJudge,
    BehaviorScenario,
    SampleResult,
    ScenarioDriver,
    ScenarioResult,
)
from storage import (
    finish_agent_eval_run,
    save_agent_eval_case_result,
    save_agent_eval_run,
)


@dataclass(frozen=True)
class BehaviorEvalConfig:
    suite_name: str = "companion_behavior"
    provider: str = "unknown"
    model: str | None = None
    prompt_version: str = "v3"
    samples_override: int | None = None
    persist: bool = False

    def __post_init__(self) -> None:
        if not self.suite_name.strip():
            raise ValueError("suite_name is required.")
        if self.samples_override is not None and self.samples_override < 1:
            raise ValueError("samples_override must be at least 1.")


async def run_behavior_evals(
    *,
    scenarios: tuple[BehaviorScenario, ...],
    driver: ScenarioDriver,
    judge: BehaviorJudge | None,
    config: BehaviorEvalConfig | None = None,
) -> BehaviorEvalReport:
    run_config = config or BehaviorEvalConfig()
    _validate_scenario_suite(scenarios)
    scenario_results: list[ScenarioResult] = []
    for scenario in scenarios:
        sample_count = run_config.samples_override or scenario.samples
        sample_results: list[SampleResult] = []
        for sample_index in range(sample_count):
            observed_turns = await driver.run_sample(scenario, sample_index)
            if len(observed_turns) != len(scenario.turns):
                raise ValueError(
                    f"Driver returned {len(observed_turns)} turns for scenario '{scenario.id}', "
                    f"expected {len(scenario.turns)}."
                )
            grades = []
            for turn_index, (scenario_turn, observed) in enumerate(
                zip(scenario.turns, observed_turns, strict=True)
            ):
                judge_result = None
                judge_error = None
                if scenario_turn.expectation.rubric:
                    if judge is None:
                        judge_error = "No semantic judge configured."
                    else:
                        try:
                            judge_result = await judge.judge(
                                scenario=scenario,
                                turn=scenario_turn,
                                observed=observed,
                                transcript=observed_turns[: turn_index + 1],
                            )
                        except Exception as error:
                            judge_error = f"{type(error).__name__}: {error}"
                grades.append(
                    combine_turn_grade(
                        scenario=scenario,
                        turn=scenario_turn,
                        observed=observed,
                        prior_turns=observed_turns[:turn_index],
                        judge_result=judge_result,
                        judge_error=judge_error,
                    )
                )
            sample_results.append(
                SampleResult(
                    scenario_id=scenario.id,
                    sample_index=sample_index,
                    passed=all(grade.passed for grade in grades),
                    turns=observed_turns,
                    grades=tuple(grades),
                )
            )
        passed_samples = sum(sample.passed for sample in sample_results)
        sample_pass_rate = passed_samples / len(sample_results)
        scenario_results.append(
            ScenarioResult(
                scenario_id=scenario.id,
                passed=sample_pass_rate >= scenario.minimum_sample_pass_rate,
                sample_pass_rate=sample_pass_rate,
                required_sample_pass_rate=scenario.minimum_sample_pass_rate,
                samples=tuple(sample_results),
            )
        )

    passed_count = sum(result.passed for result in scenario_results)
    failed_count = len(scenario_results) - passed_count
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "provider": run_config.provider,
        "model": run_config.model,
        "prompt_version": run_config.prompt_version,
        "semantic_judge_enabled": judge is not None,
        "sample_count": sum(len(result.samples) for result in scenario_results),
    }
    report = BehaviorEvalReport(
        suite_name=run_config.suite_name,
        passed=failed_count == 0,
        scenario_passed=passed_count,
        scenario_failed=failed_count,
        scenarios=tuple(scenario_results),
        metadata=metadata,
    )
    if run_config.persist:
        run_id = _persist_report(report, run_config)
        report = BehaviorEvalReport(
            suite_name=report.suite_name,
            passed=report.passed,
            scenario_passed=report.scenario_passed,
            scenario_failed=report.scenario_failed,
            scenarios=report.scenarios,
            metadata={**report.metadata, "run_id": run_id},
        )
    return report


def report_payload(report: BehaviorEvalReport) -> dict[str, Any]:
    return {
        "suite_name": report.suite_name,
        "passed": report.passed,
        "scenario_passed": report.scenario_passed,
        "scenario_failed": report.scenario_failed,
        "metadata": report.metadata,
        "scenarios": [
            {
                "scenario_id": scenario.scenario_id,
                "passed": scenario.passed,
                "sample_pass_rate": scenario.sample_pass_rate,
                "required_sample_pass_rate": scenario.required_sample_pass_rate,
                "samples": [
                    {
                        "sample_index": sample.sample_index,
                        "passed": sample.passed,
                        "turns": [
                            {
                                "turn_index": turn.turn_index,
                                "user_message": turn.user_message,
                                "assistant_reply": turn.assistant_reply,
                                "assistant_messages": list(turn.assistant_messages),
                                "trace_steps": list(turn.trace_steps),
                                "direct_reply_reason": turn.direct_reply_reason,
                                "context_summary": turn.context_summary,
                                "conversation_id": turn.conversation_id,
                                "user_id": turn.user_id,
                            }
                            for turn in sample.turns
                        ],
                        "grades": [
                            {
                                "turn_index": grade.turn_index,
                                "passed": grade.passed,
                                "weighted_score": grade.weighted_score,
                                "judge_error": grade.judge_error,
                                "findings": [
                                    {
                                        "code": finding.code,
                                        "message": finding.message,
                                        "severity": finding.severity,
                                        "evidence": finding.evidence,
                                    }
                                    for finding in grade.findings
                                ],
                                "dimension_grades": [
                                    {
                                        "dimension_id": dimension.dimension_id,
                                        "score": dimension.score,
                                        "reason": dimension.reason,
                                    }
                                    for dimension in grade.dimension_grades
                                ],
                            }
                            for grade in sample.grades
                        ],
                    }
                    for sample in scenario.samples
                ],
            }
            for scenario in report.scenarios
        ],
    }


def _validate_scenario_suite(scenarios: tuple[BehaviorScenario, ...]) -> None:
    if not scenarios:
        raise ValueError("Behavior eval suite needs at least one scenario.")
    scenario_ids = [scenario.id for scenario in scenarios]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("Behavior eval scenario ids must be unique.")


def _persist_report(report: BehaviorEvalReport, config: BehaviorEvalConfig) -> str:
    run = save_agent_eval_run(
        {
            "suite_name": config.suite_name,
            "provider": config.provider,
            "model": config.model,
            "status": "running",
            "metadata": report.metadata,
        }
    )
    payload = report_payload(report)
    for scenario in payload["scenarios"]:
        failures = [
            {
                "sample_index": sample["sample_index"],
                "grades": [grade for grade in sample["grades"] if not grade["passed"]],
            }
            for sample in scenario["samples"]
            if not sample["passed"]
        ]
        save_agent_eval_case_result(
            {
                "run_id": run["id"],
                "case_id": scenario["scenario_id"],
                "status": "passed" if scenario["passed"] else "failed",
                "failures": failures,
                "expected": {
                    "required_sample_pass_rate": scenario["required_sample_pass_rate"],
                },
                "observed": scenario,
                "trace_count": sum(
                    len(sample["turns"]) for sample in scenario["samples"]
                ),
            }
        )
    finish_agent_eval_run(
        run["id"],
        status="passed" if report.passed else "failed",
        passed=report.scenario_passed,
        failed=report.scenario_failed,
        total=len(report.scenarios),
        metadata=report.metadata,
    )
    return str(run["id"])
