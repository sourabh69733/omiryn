"""Checks completeness and structural safety of thread-management evaluation cases."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from agent.evals.behavior.reporting.writer import save_evaluation_reports
from agent.evals.behavior.simulation import thread_runner
from agent.evals.behavior.simulation.runtime import RuntimeDriverConfig
from agent.evals.behavior.simulation.thread_scenario import (
    THREAD_MANAGEMENT_SCENARIOS,
    ExpectedThreadAction,
    ExistingThreadFixture,
    ThreadManagementScenario,
    get_thread_management_scenario,
    list_thread_management_scenarios,
)
from agent.evals.behavior.simulation.thread_runner import _grade_shadow_proposal


class ConversationThreadScenarioTest(unittest.TestCase):
    def test_catalogue_covers_each_operation_and_no_update(self) -> None:
        operations = {
            scenario.expected_action.operation
            for scenario in THREAD_MANAGEMENT_SCENARIOS
            if scenario.expected_action is not None
        }

        self.assertEqual(
            operations,
            {"create", "continue", "switch", "pause", "complete", "block"},
        )
        self.assertTrue(
            any(scenario.expected_action is None for scenario in THREAD_MANAGEMENT_SCENARIOS)
        )

    def test_catalogue_covers_deduplication_random_talk_and_cross_session_resume(self) -> None:
        tags = {tag for scenario in THREAD_MANAGEMENT_SCENARIOS for tag in scenario.tags}

        self.assertTrue({"deduplication", "random_talk", "cross_session"}.issubset(tags))
        self.assertGreaterEqual(len(THREAD_MANAGEMENT_SCENARIOS), 10)

    def test_scenario_ids_are_unique_and_expected_threads_exist(self) -> None:
        scenario_ids = [scenario.id for scenario in THREAD_MANAGEMENT_SCENARIOS]
        self.assertEqual(len(scenario_ids), len(set(scenario_ids)))

        for scenario in THREAD_MANAGEMENT_SCENARIOS:
            with self.subTest(scenario=scenario.id):
                thread_ids = {thread.id for thread in scenario.existing_threads}
                if scenario.expected_action and scenario.expected_action.thread_id:
                    self.assertIn(scenario.expected_action.thread_id, thread_ids)

    def test_tag_filter_and_id_lookup(self) -> None:
        deduplication = list_thread_management_scenarios(tags=("deduplication",))

        self.assertEqual(len(deduplication), 2)
        self.assertEqual(
            get_thread_management_scenario("pause_unfinished_thread").expected_action.operation,
            "pause",
        )
        with self.assertRaisesRegex(ValueError, "Unknown thread scenario"):
            get_thread_management_scenario("missing")

    def test_invalid_active_thread_fixture_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Only an open thread can be active"):
            ExistingThreadFixture(
                id="closed",
                title="Closed subject",
                summary="Already closed.",
                status="completed",
                active=True,
            )

    def test_existing_operation_must_reference_a_fixture(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown thread id"):
            ThreadManagementScenario(
                id="invalid-reference",
                description="Invalid reference should fail immediately.",
                prior_messages=(),
                user_message="Continue that topic.",
                expected_action=ExpectedThreadAction(
                    operation="continue",
                    thread_id="missing-thread",
                    reason="Structural validation test.",
                ),
            )

    def test_shadow_grader_accepts_matching_existing_thread_operation(self) -> None:
        expected = ExpectedThreadAction(
            operation="continue",
            thread_id="logical-thread",
            reason="The subject continues.",
        )
        shadow = {
            "present": True,
            "valid": True,
            "proposal": {
                "thread_updates": [
                    {"operation": "continue", "thread_id": "persisted-thread"}
                ]
            },
            "errors": [],
        }

        passed, _ = _grade_shadow_proposal(
            expected=expected,
            shadow=shadow,
            fixture_ids={"logical-thread": "persisted-thread"},
        )

        self.assertTrue(passed)

    def test_shadow_grader_rejects_missing_output_after_model_call(self) -> None:
        passed, finding = _grade_shadow_proposal(
            expected=None,
            shadow={
                "present": False,
                "valid": False,
                "proposal": None,
                "errors": ["missing"],
                "model_called": True,
            },
            fixture_ids={},
        )

        self.assertFalse(passed)
        self.assertIn("returned no thread shadow proposal", finding)

    def test_thread_report_is_readable_and_saved_in_ist_day_folder(self) -> None:
        payload = {
            "stage": "thread_management_shadow_eval",
            "passed": False,
            "judges": ["deterministic thread expectation"],
            "run": {
                "finished_at": "2026-08-17T20:00:00+00:00",
                "duration_seconds": 1.25,
                "api_calls": 1,
            },
            "companion": {
                "agent_name": "Mira",
                "provider": "deepinfra",
                "model": "example-model",
                "prompt_version": "v3-1",
            },
            "summary": {"total": 1, "passed": 0, "failed": 1},
            "scenarios": [
                {
                    "scenario_id": "continue_active_thread",
                    "description": "Continue the active subject.",
                    "passed": False,
                    "input": {
                        "prior_messages": [],
                        "user_message": "I am still worried about changing careers.",
                        "existing_threads": [
                            {
                                "id": "career-thread",
                                "title": "Career change",
                                "status": "open",
                                "active": True,
                                "from_previous_conversation": False,
                            }
                        ],
                    },
                    "expected": {
                        "operation": "continue",
                        "thread_id": "career-thread",
                        "reason": "Same durable subject.",
                    },
                    "observed": {
                        "assistant_reply": "That uncertainty makes sense.",
                        "operations": ["create"],
                        "shadow_present": True,
                        "shadow_valid": True,
                        "proposal": {
                            "thread_updates": [
                                {
                                    "operation": "create",
                                    "thread": {"title": "Career uncertainty"},
                                }
                            ]
                        },
                        "validation_errors": [],
                    },
                    "finding": "Expected continue, but received create.",
                }
            ],
        }

        with TemporaryDirectory() as directory:
            paths = save_evaluation_reports(
                payload,
                output_dir=Path(directory),
                now=datetime(2026, 8, 17, 20, 0, tzinfo=timezone.utc),
            )
            markdown = paths.markdown.read_text(encoding="utf-8")
            history = paths.history.read_text(encoding="utf-8")

        self.assertEqual(paths.markdown.parent.name, "2026-08-18")
        self.assertIn("__thread_shadow__fail.md", paths.markdown.name)
        self.assertIn("Expected action:** continue", markdown)
        self.assertIn("Observed actions:** create", markdown)
        self.assertIn("Career change", markdown)
        self.assertIn("Thread management shadow eval", history)
        self.assertIn("0%", history)


class BackgroundConversationThreadScenarioTest(unittest.IsolatedAsyncioTestCase):
    async def test_background_runner_reuses_thread_scenario_and_calls_model_once(self) -> None:
        function = getattr(thread_runner, "run_background_thread_management_scenario", None)
        self.assertTrue(
            callable(function), "run_background_thread_management_scenario is missing"
        )
        scenario = get_thread_management_scenario("continue_active_thread")

        async def model_result(prompt: str, **_: object) -> dict[str, object]:
            payload = json.loads(prompt)
            active = next(thread for thread in payload["existing_threads"] if thread["active"])
            return {
                "decision": "propose",
                "operations": [],
                "thread_operation": {
                    "operation": "continue",
                    "thread_id": active["id"],
                    "summary": "The user remains worried about career-change stability.",
                    "depth": "explored",
                },
                "handoff": {
                    "summary": "Career change remains unresolved.",
                    "active_people": [],
                    "active_topics": ["career change"],
                    "unresolved_references": [],
                },
            }

        with patch(
            "agent.cognition.background.service.analyze_background_cognition",
            new_callable=AsyncMock,
            side_effect=model_result,
        ) as analyze:
            result = await function(
                scenario=scenario,
                companion=RuntimeDriverConfig(provider="mock", model="cognition-model"),
            )

        self.assertEqual(analyze.await_count, 1)
        self.assertTrue(result.passed)
        self.assertEqual(result.actual_operations, ("continue",))
        self.assertEqual(result.assistant_reply, "")


if __name__ == "__main__":
    unittest.main()
