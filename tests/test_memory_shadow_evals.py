"""Checks the Phase 3 memory catalogue, grader, runner, and readable reports."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from agent.evals.behavior.reporting.writer import save_evaluation_reports
from agent.evals.memory.runner import (
    grade_memory_shadow_result,
    run_memory_shadow_scenario,
    scenario_result_payload,
)
from agent.evals.memory.scenarios import (
    MEMORY_SHADOW_SCENARIOS,
    get_memory_shadow_scenario,
    list_memory_shadow_scenarios,
)
from storage import reset_db


class MemoryShadowEvaluationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()

    def test_catalogue_covers_required_phase_three_risks(self) -> None:
        tags = {tag for scenario in MEMORY_SHADOW_SCENARIOS for tag in scenario.tags}

        self.assertTrue(
            {
                "profile_fact",
                "matching_fact",
                "deduplication",
                "correction",
                "assistant_contamination",
                "cross_batch",
                "chat_learning",
                "temporary_context",
                "no_change",
                "hinglish",
            }.issubset(tags)
        )
        self.assertGreaterEqual(len(MEMORY_SHADOW_SCENARIOS), 10)
        self.assertEqual(
            len({scenario.id for scenario in MEMORY_SHADOW_SCENARIOS}),
            len(MEMORY_SHADOW_SCENARIOS),
        )

    def test_lookup_and_tag_filter_are_stable(self) -> None:
        corrections = list_memory_shadow_scenarios(tags=("correction",))

        self.assertEqual(
            {scenario.id for scenario in corrections},
            {
                "supersede_corrected_location",
                "retract_withdrawn_partner_location_filter",
            },
        )
        self.assertEqual(
            get_memory_shadow_scenario("capture_current_location_profile_fact")
            .expected_operations[0]
            .data_point_type,
            "profile_fact",
        )
        with self.assertRaisesRegex(ValueError, "Unknown memory shadow scenario"):
            get_memory_shadow_scenario("missing")

    def test_grader_accepts_semantic_wording_and_exact_evidence(self) -> None:
        scenario = get_memory_shadow_scenario("capture_partner_location_preference")
        operation = {
            "operation": "add",
            "target_memory_id": None,
            "data_point_type": "matching_fact",
            "category": "partner_location",
            "key": "preferred_partner_location",
            "label": "Prefers a partner near Chennai",
            "value": {"state": "Tamil Nadu", "city": "Chennai"},
            "confidence": 0.94,
            "evidence_message_indexes": [0],
        }

        passed, findings = grade_memory_shadow_result(
            scenario=scenario,
            decision="propose",
            operations=(operation,),
            structurally_valid=True,
        )

        self.assertTrue(passed)
        self.assertIn("matched", findings[0])

    def test_grader_rejects_duplicate_and_wrong_classification(self) -> None:
        scenario = get_memory_shadow_scenario("capture_current_location_profile_fact")
        wrong = {
            "operation": "add",
            "data_point_type": "matching_fact",
            "label": "Lives in Pune",
            "value": "Pune",
            "evidence_message_indexes": [1],
        }

        passed, findings = grade_memory_shadow_result(
            scenario=scenario,
            decision="propose",
            operations=(wrong, wrong),
            structurally_valid=True,
        )

        self.assertFalse(passed)
        self.assertIn("Unexpected operation", " ".join(findings))
        self.assertIn("Missing expected operation", " ".join(findings))

    def test_grader_accepts_meaning_preserving_chat_learning_summary(self) -> None:
        scenario = get_memory_shadow_scenario("capture_conversation_style_learning")
        operation = {
            "operation": "add",
            "target_memory_id": None,
            "data_point_type": "chat_learning",
            "category": "conversation_style",
            "key": "question_frequency",
            "label": "preference for question frequency",
            "value": "less frequent",
            "confidence": 1.0,
            "evidence_message_indexes": [0],
        }

        passed, _ = grade_memory_shadow_result(
            scenario=scenario,
            decision="propose",
            operations=(operation,),
            structurally_valid=True,
        )

        self.assertTrue(passed)

    def test_grader_accepts_core_temporary_context_without_every_source_detail(self) -> None:
        scenario = get_memory_shadow_scenario("capture_short_lived_health_context")
        operation = {
            "operation": "add",
            "target_memory_id": None,
            "data_point_type": "temporary_context",
            "category": "health",
            "key": "current_status",
            "label": "current health status",
            "value": "sick",
            "confidence": 1.0,
            "evidence_message_indexes": [0],
        }

        passed, _ = grade_memory_shadow_result(
            scenario=scenario,
            decision="propose",
            operations=(operation,),
            structurally_valid=True,
        )

        self.assertTrue(passed)

    def test_grader_accepts_distinct_optional_fact_but_still_rejects_duplicates(self) -> None:
        scenario = get_memory_shadow_scenario("capture_hinglish_partner_personality")
        required = {
            "operation": "add",
            "target_memory_id": None,
            "data_point_type": "matching_fact",
            "category": "partner_pref",
            "key": "personality_traits",
            "label": "prefers calm and funny partner",
            "value": ["calm", "funny"],
            "confidence": 0.8,
            "evidence_message_indexes": [0],
        }
        optional = {
            "operation": "add",
            "target_memory_id": None,
            "data_point_type": "matching_fact",
            "category": "partner_pref",
            "key": "loudness_tolerance",
            "label": "does not prefer loud partner",
            "value": "low",
            "confidence": 0.8,
            "evidence_message_indexes": [0],
        }

        accepted, _ = grade_memory_shadow_result(
            scenario=scenario,
            decision="propose",
            operations=(required, optional),
            structurally_valid=True,
        )
        duplicate_accepted, _ = grade_memory_shadow_result(
            scenario=scenario,
            decision="propose",
            operations=(required, required),
            structurally_valid=True,
        )

        self.assertTrue(accepted)
        self.assertFalse(duplicate_accepted)

    async def test_runner_calls_real_memory_boundary_and_returns_report_payload(self) -> None:
        scenario = get_memory_shadow_scenario(
            "use_previous_batch_context_without_using_it_as_evidence"
        )
        raw = {
            "decision": "propose",
            "operations": [
                {
                    "operation": "add",
                    "target_memory_id": None,
                    "data_point_type": "matching_fact",
                    "category": "partner_personality",
                    "key": "preferred_partner_traits",
                    "label": "Prefers calm and funny partners",
                    "value": ["calm", "funny", "not loud"],
                    "confidence": 0.9,
                    "evidence_message_indexes": [2],
                }
            ],
            "thread_operation": {"operation": "none"},
            "handoff": {
                "summary": "The user described preferred partner personality.",
                "active_people": [],
                "active_topics": ["partner personality"],
                "unresolved_references": [],
            },
        }
        with patch(
            "agent.evals.memory.runner.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=raw,
            create=True,
        ) as analyze:
            result = await run_memory_shadow_scenario(
                scenario=scenario,
                model="memory-model",
                timeout_seconds=30,
            )

        self.assertTrue(result.passed)
        prompt = analyze.await_args.args[0]
        self.assertIn('"scope":"context"', prompt)
        self.assertIn('"scope":"new"', prompt)
        self.assertIn('"evidence_eligible":false', prompt)
        payload = scenario_result_payload(result, scenario=scenario)
        self.assertEqual(payload["observed"]["operations"][0]["evidence_message_indexes"], [2])

    def test_memory_report_is_readable_and_saved_in_ist_day_folder(self) -> None:
        payload = {
            "stage": "memory_shadow_eval",
            "passed": False,
            "judges": ["deterministic memory expectation"],
            "run": {
                "finished_at": "2026-08-21T20:00:00+00:00",
                "duration_seconds": 1.25,
                "api_calls": 1,
            },
            "companion": {
                "agent_name": "Background memory extractor",
                "provider": "deepinfra",
                "model": "example-model",
                "prompt_version": "memory-v2",
            },
            "summary": {
                "total": 1,
                "passed": 0,
                "failed": 1,
                "structural_failures": 0,
                "live_memory_writes": False,
            },
            "scenarios": [
                {
                    "scenario_id": "capture_current_location_profile_fact",
                    "description": "Capture a stable location.",
                    "passed": False,
                    "input": {
                        "messages": [{"role": "user", "content": "I live in Pune."}],
                        "processed_through_message_index": -1,
                        "existing_memories": [],
                    },
                    "expected": {
                        "decision": "propose",
                        "operations": [
                            {
                                "operation": "add",
                                "data_point_type": "profile_fact",
                                "value_concepts": ["pune"],
                                "evidence_message_indexes": [0],
                            }
                        ],
                    },
                    "observed": {
                        "decision": "no_change",
                        "operations": [],
                        "structurally_valid": True,
                        "validation_errors": [],
                        "duration_seconds": 1.0,
                    },
                    "findings": ["Expected propose, observed no_change."],
                }
            ],
        }

        with TemporaryDirectory() as directory:
            paths = save_evaluation_reports(
                payload,
                output_dir=Path(directory),
                now=datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc),
            )
            markdown = paths.markdown.read_text(encoding="utf-8")
            history = paths.history.read_text(encoding="utf-8")

        self.assertEqual(paths.markdown.parent.name, "2026-08-22")
        self.assertIn("__memory_shadow__fail.md", paths.markdown.name)
        self.assertIn("# Background Memory Evaluation Report", markdown)
        self.assertIn("Extractor model:** example-model", markdown)
        self.assertIn("Live memory writes:** disabled", markdown)
        self.assertIn("Expected decision:** propose", markdown)
        self.assertIn("I live in Pune", markdown)
        self.assertIn("Memory shadow eval", history)
        self.assertIn("0%", history)


if __name__ == "__main__":
    unittest.main()
