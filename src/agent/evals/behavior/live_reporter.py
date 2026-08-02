from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from io import TextIOBase
from time import perf_counter

from agent.evals.behavior.events import EvalEvent


@dataclass(frozen=True)
class LiveRunStats:
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    api_calls: int


class TerminalProgressReporter:
    """Renders evaluation events in simple language as work completes."""

    def __init__(self, stream: TextIOBase | None = None, *, enabled: bool = True) -> None:
        self.stream = stream or sys.stderr
        self.enabled = enabled
        self.started_at = datetime.now(timezone.utc)
        self._started_clock = perf_counter()
        self.api_calls = 0

    def __call__(self, event: EvalEvent) -> None:
        if event.kind in {
            "judge_call_started",
            "companion_api_call_completed",
            "simulated_user_call_started",
        }:
            self.api_calls += 1
        if not self.enabled:
            return
        rendered = _render_event(event)
        if rendered:
            print(rendered, file=self.stream, flush=True)

    def stats(self) -> LiveRunStats:
        finished_at = datetime.now(timezone.utc)
        return LiveRunStats(
            started_at=self.started_at,
            finished_at=finished_at,
            duration_seconds=round(perf_counter() - self._started_clock, 3),
            api_calls=self.api_calls,
        )


def _render_event(event: EvalEvent) -> str | None:
    data = event.data
    if event.kind == "calibration_started":
        return f"\nChecking the judge models with {data['total_cases']} known examples..."
    if event.kind == "calibration_case_started":
        return (
            f"  Judge check {data['case_number']}/{data['total_cases']}: "
            f"{_plain_name(data['case_id'])}"
        )
    if event.kind == "judge_call_started":
        purpose = "repairing its answer" if data.get("purpose") == "repair" else "reviewing"
        return (
            f"    {data['judge_name']} is {purpose} "
            f"(attempt {data['attempt']}/{data['max_attempts']})..."
        )
    if event.kind == "judge_call_retry":
        return f"    {data['judge_name']} had a temporary problem: {data['error']}. Trying again..."
    if event.kind == "judge_call_completed":
        return f"    {data['judge_name']} responded in {data['duration_seconds']:.1f}s."
    if event.kind == "judge_call_failed":
        return f"    {data['judge_name']} failed: {data['error']}"
    if event.kind == "calibration_case_completed":
        status = "PASS" if data["passed"] else "FAIL"
        detail = f" — {data['judge_error']}" if data.get("judge_error") else ""
        return f"    {status}{detail}"
    if event.kind == "calibration_completed":
        status = "PASSED" if data["passed"] else "FAILED"
        return (
            f"Judge reliability check {status}: {data['completed_cases']}/"
            f"{data['total_cases']} examples completed, "
            f"{data['judge_errors']} judge errors."
        )
    if event.kind == "scenario_started":
        return f"\nScenario: {_plain_name(data['scenario_id'])}"
    if event.kind == "simulated_conversation_started":
        return (
            f"\nAI-user scenario: {_plain_name(data['scenario_id'])} "
            f"(up to {data['maximum_turns']} turns)"
        )
    if event.kind == "simulated_user_call_started":
        activities = {
            "judgment": "judging the conversation",
            "judgment_repair": "repairing its verdict format",
            "conversation_repair": "repairing its message format",
        }
        activity = activities.get(data.get("purpose"), "thinking")
        return (
            f"    AI User ({data['model_name']}) is {activity} "
            f"(attempt {data['attempt']}/{data['max_attempts']})..."
        )
    if event.kind == "simulated_user_call_retry":
        role = "judge" if str(data.get("purpose", "")).startswith("judgment") else "user"
        return f"    AI {role} had a temporary problem: {data['error']}. Trying again..."
    if event.kind == "simulated_user_call_failed":
        role = "judge" if str(data.get("purpose", "")).startswith("judgment") else "user"
        return f"    AI {role} call failed: {data['error']}"
    if event.kind == "simulated_user_finished":
        return "    AI User chose to end the conversation naturally."
    if event.kind == "user_judgment_started":
        return "    AI User is now judging how the conversation felt..."
    if event.kind == "user_judgment_completed":
        status = "PASS" if data["passed"] else "FAIL"
        continuation = "yes" if data["would_continue"] else "no"
        lines = [
            f"    AI-user verdict: {status} — {data['average_score']:.1f}/4, "
            f"would continue: {continuation}"
        ]
        for dimension in data.get("dimensions", []):
            lines.append(
                f"      {_plain_name(dimension['dimension_id'])}: "
                f"{dimension['score']}/4 — {dimension['reason']}"
            )
        return "\n".join(lines)
    if event.kind == "independent_judgment_started":
        return f"    {data['judge_name']} is reviewing the full conversation..."
    if event.kind == "independent_judgment_completed":
        status = "PASS" if data["passed"] else "FAIL"
        continuation = "yes" if data["would_continue"] else "no"
        lines = [
            f"    {data['judge_name']} verdict: {status} — "
            f"{data['average_score']:.1f}/4, would continue: {continuation}"
        ]
        for dimension in data.get("dimensions", []):
            lines.append(
                f"      {_plain_name(dimension['dimension_id'])}: "
                f"{dimension['score']}/4 — {dimension['reason']}"
            )
        return "\n".join(lines)
    if event.kind == "independent_judgment_failed":
        return f"    {data['judge_name']} failed: {data['error']}"
    if event.kind == "sample_started":
        return f"  Conversation {data['sample_number']}/{data['sample_count']}"
    if event.kind == "user_turn":
        return f"    {data.get('speaker_label', 'User')}: {data['message']}"
    if event.kind == "companion_call_started":
        return f"    Companion ({data['model_name']}) is replying..."
    if event.kind == "companion_turn":
        return f"    Companion: {data['message']}"
    if event.kind == "companion_call_failed":
        return f"    Companion call failed: {data['error']}"
    if event.kind == "turn_grading_started":
        return f"    Reviewing turn {data['turn_number']}..."
    if event.kind == "turn_graded":
        status = "PASS" if data["passed"] else "FAIL"
        score = data.get("weighted_score")
        score_text = f", score {score:.1f}/4" if score is not None else ""
        lines = [f"    Turn result: {status}{score_text}"]
        for dimension in data.get("dimensions", []):
            lines.append(
                f"      {_plain_name(dimension['id'])}: {dimension['score']}/4 — "
                f"{dimension['reason']}"
            )
        for finding in data.get("findings", []):
            lines.append(f"      Problem: {finding}")
        return "\n".join(lines)
    if event.kind == "sample_completed":
        return f"  Conversation result: {'PASS' if data['passed'] else 'FAIL'}"
    if event.kind == "scenario_completed":
        return (
            f"Scenario result: {'PASS' if data['passed'] else 'FAIL'} — "
            f"{data['passed_samples']}/{data['sample_count']} conversations passed."
        )
    if event.kind == "evaluation_completed":
        return (
            "\nEvaluation complete: "
            f"{'PASS' if data['passed'] else 'FAIL'} — "
            f"{data['scenario_passed']}/{data['scenario_total']} scenarios passed."
        )
    if event.kind == "simulated_conversation_completed":
        passed = data.get("passed")
        status = "PENDING independent judge" if passed is None else ("PASS" if passed else "FAIL")
        return (
            f"\nConversation captured: {data['turn_count']} turns. "
            f"Consensus result: {status}."
        )
    return None


def _plain_name(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()
