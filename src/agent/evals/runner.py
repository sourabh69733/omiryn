from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from agent.runtime.orchestrator import run_agent_turn
from storage import (
    finish_agent_eval_run,
    list_agent_trace_steps,
    list_agent_traces,
    list_profile_facts,
    reset_db,
    save_agent_eval_case_result,
    save_agent_eval_run,
    save_conversation,
)

EXPECTED_TRACE_STEPS = [
    "input_guardrail",
    "memory_write",
    "retrieval",
    "context_pack",
    "model_call",
    "context_snapshot",
]


@dataclass(frozen=True)
class AgentEvalCase:
    id: str
    user_messages: list[str]
    expected_facts: set[tuple[str, str]] = field(default_factory=set)
    expected_trace_steps: list[str] = field(default_factory=lambda: EXPECTED_TRACE_STEPS)


@dataclass(frozen=True)
class AgentEvalResult:
    case_id: str
    passed: bool
    failures: list[str]
    expected_facts: list[tuple[str, str]]
    observed_facts: list[tuple[str, str]]
    expected_trace_steps: list[str]
    observed_trace_steps: list[str]
    trace_count: int


EVAL_CASES = [
    AgentEvalCase(
        id="intent_city_values_dealbreaker",
        user_messages=[
            (
                "I want a long-term relationship in Bengaluru. Family and emotional "
                "maturity matter to me, I prefer calm people, and smoking is a dealbreaker."
            )
        ],
        expected_facts={
            ("dating_intent", "relationship_intent"),
            ("location", "city"),
            ("values", "family"),
            ("values", "emotional_maturity"),
            ("communication", "calm_low_drama"),
            ("dealbreakers", "smoking"),
        },
    ),
    AgentEvalCase(
        id="career_respect_calm",
        user_messages=[
            "Career growth, mutual respect, and calm communication matter to me in relationships.",
            "I like thoughtful conversation and clear communication.",
        ],
        expected_facts={
            ("values", "ambition"),
            ("values", "mutual_respect"),
            ("communication", "calm_low_drama"),
            ("communication", "thoughtful"),
            ("communication", "direct"),
        },
    ),
]


async def run_agent_evals(
    reset: bool = True,
    persist: bool = True,
    suite_name: str = "agent_regression",
) -> dict[str, Any]:
    os.environ["AGENT_PROVIDER"] = "mock"
    os.environ["AUTH_REQUIRED"] = "false"
    os.environ["DATA_POINT_EXTRACTOR"] = "rules"
    if reset:
        reset_db()

    eval_run = (
        save_agent_eval_run(
            {
                "suite_name": suite_name,
                "provider": os.getenv("AGENT_PROVIDER", "mock"),
                "model": "mock",
                "status": "running",
                "metadata": {
                    "case_count": len(EVAL_CASES),
                    "runner": "agent.evals.runner",
                },
            }
        )
        if persist
        else None
    )
    results = [await _run_case(case) for case in EVAL_CASES]
    passed = sum(1 for result in results if result.passed)
    failed = len(results) - passed
    if eval_run:
        for result in results:
            save_agent_eval_case_result(
                {
                    "run_id": eval_run["id"],
                    "case_id": result.case_id,
                    "status": "passed" if result.passed else "failed",
                    "failures": result.failures,
                    "expected": {
                        "facts": _fact_payload(result.expected_facts),
                        "trace_steps": result.expected_trace_steps,
                    },
                    "observed": {
                        "facts": _fact_payload(result.observed_facts),
                        "trace_steps": result.observed_trace_steps,
                    },
                    "trace_count": result.trace_count,
                }
            )
        finish_agent_eval_run(
            eval_run["id"],
            status="passed" if failed == 0 else "failed",
            passed=passed,
            failed=failed,
            total=len(results),
        )

    return {
        "run_id": eval_run["id"] if eval_run else None,
        "suite_name": suite_name,
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "results": [_result_payload(result) for result in results],
    }


async def _run_case(case: AgentEvalCase) -> AgentEvalResult:
    user_id = f"eval-{case.id}-{uuid4().hex[:8]}"
    conversation_id = f"eval-conversation-{uuid4().hex}"
    messages: list[dict[str, Any]] = [
        {"role": "assistant", "content": "Hey, I'm Mira. Tell me what matters to you."}
    ]
    save_conversation(
        {
            "id": conversation_id,
            "user_id": user_id,
            "status": "active",
            "agent_provider": "mock",
            "agent_model": "mock",
            "agent_mode": "know_me",
            "agent_tone": "auto",
            "messages": messages,
        },
        user_id,
    )

    for user_text in case.user_messages:
        turn = await run_agent_turn(
            conversation_id=conversation_id,
            messages=messages,
            user_text=user_text,
            user_id=user_id,
            user_profile={
                "user_id": user_id,
                "display_name": "Eval User",
                "gender": "man",
                "interested_in": "women",
            },
            model="mock",
            agent_mode="know_me",
            agent_tone="auto",
            style_source_id=None,
        )
        messages = turn.messages
        save_conversation(
            {
                "id": conversation_id,
                "user_id": user_id,
                "status": "active",
                "agent_provider": "mock",
                "agent_model": "mock",
                "agent_mode": "know_me",
                "agent_tone": "auto",
                "messages": messages,
            },
            user_id,
        )

    observed_facts = sorted(
        {
            (str(fact["category"]), str(fact["key"]))
            for fact in list_profile_facts(user_id)
        }
    )
    traces = list_agent_traces(conversation_id, user_id)
    trace_steps = list_agent_trace_steps(
        trace_id=traces[0]["id"] if traces else None,
        user_id=user_id,
    )
    observed_trace_steps = [str(step["step_name"]) for step in trace_steps]
    failures = _case_failures(case, observed_facts, observed_trace_steps, traces)
    return AgentEvalResult(
        case_id=case.id,
        passed=not failures,
        failures=failures,
        expected_facts=sorted(case.expected_facts),
        observed_facts=observed_facts,
        expected_trace_steps=case.expected_trace_steps,
        observed_trace_steps=observed_trace_steps,
        trace_count=len(traces),
    )


def _case_failures(
    case: AgentEvalCase,
    observed_facts: list[tuple[str, str]],
    observed_trace_steps: list[str],
    traces: list[dict[str, Any]],
) -> list[str]:
    failures = []
    missing_facts = sorted(case.expected_facts - set(observed_facts))
    if missing_facts:
        failures.append(f"missing facts: {missing_facts}")
    if not traces:
        failures.append("missing trace")
    elif traces[0].get("status") != "completed":
        failures.append(f"latest trace status was {traces[0].get('status')}")
    if observed_trace_steps[: len(case.expected_trace_steps)] != case.expected_trace_steps:
        failures.append(
            "trace steps mismatch: "
            f"expected {case.expected_trace_steps}, observed {observed_trace_steps}"
        )
    return failures


def _result_payload(result: AgentEvalResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "passed": result.passed,
        "failures": result.failures,
        "expected_facts": _fact_payload(result.expected_facts),
        "observed_facts": _fact_payload(result.observed_facts),
        "expected_trace_steps": result.expected_trace_steps,
        "observed_trace_steps": result.observed_trace_steps,
        "trace_count": result.trace_count,
    }


def _fact_payload(facts: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"category": category, "key": key}
        for category, key in facts
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Omiryn agent evals.")
    parser.add_argument("--no-reset", action="store_true", help="Do not reset the configured eval DB.")
    parser.add_argument("--no-persist", action="store_true", help="Do not write eval run rows.")
    parser.add_argument("--suite", default="agent_regression", help="Eval suite name.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    report = asyncio.run(
        run_agent_evals(
            reset=not args.no_reset,
            persist=not args.no_persist,
            suite_name=args.suite,
        )
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Agent evals: {report['passed']}/{report['total']} passed")
        for result in report["results"]:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{status} {result['case_id']}")
            for failure in result["failures"]:
                print(f"  - {failure}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
