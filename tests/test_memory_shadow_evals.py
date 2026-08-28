"""Checks the Phase 3 memory catalogue, grader, runner, and readable reports."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from agent.evals.behavior.reporting.writer import save_evaluation_reports
from agent.evals.memory.judge import MemoryEvidenceJudgment, MemoryOperationJudgment
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
                "temporary_context_rejected",
                "no_change",
                "hinglish",
            }.issubset(tags)
        )
        self.assertGreaterEqual(len(MEMORY_SHADOW_SCENARIOS), 14)
        self.assertEqual(
            len({scenario.id for scenario in MEMORY_SHADOW_SCENARIOS}),
            len(MEMORY_SHADOW_SCENARIOS),
        )

    def test_memory_eligibility_regressions_protect_incidental_content(self) -> None:
        """Technical content and names alone must never be treated as user memory."""
        rejected_ids = {
            "ignore_technical_explanation",
            "ignore_code_example",
            "ignore_product_name_without_personal_claim",
            "ignore_short_lived_health_context_without_expiry",
        }
        rejected = [get_memory_shadow_scenario(scenario_id) for scenario_id in rejected_ids]

        self.assertTrue(all(scenario.expected_decision == "no_change" for scenario in rejected))
        work_fact = get_memory_shadow_scenario("capture_explicit_work_background_as_profile_fact")
        expected = work_fact.expected_operations[0]
        self.assertEqual(expected.data_point_type, "profile_fact")
        self.assertEqual(expected.memory_basis, "stable_user_attribute")

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
            "memory_basis": "explicit_matching_preference",
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

    def test_grader_accepts_split_profile_facts_for_explicit_work_background(self) -> None:
        """One explicit work statement may safely yield more than one profile fact."""
        scenario = get_memory_shadow_scenario("capture_explicit_work_background_as_profile_fact")
        operations = (
            {
                "operation": "add",
                "target_memory_id": None,
                "data_point_type": "profile_fact",
                "memory_basis": "stable_user_attribute",
                "category": "work",
                "key": "product_builder",
                "label": "Builds a matchmaking product",
                "value": "Omiryn",
                "confidence": 0.9,
                "evidence_message_indexes": [0],
            },
            {
                "operation": "add",
                "target_memory_id": None,
                "data_point_type": "profile_fact",
                "memory_basis": "stable_user_attribute",
                "category": "work",
                "key": "product_name",
                "label": "Product being built",
                "value": "Omiryn",
                "confidence": 0.9,
                "evidence_message_indexes": [0],
            },
        )

        passed, findings = grade_memory_shadow_result(
            scenario=scenario,
            decision="propose",
            operations=operations,
            structurally_valid=True,
        )

        self.assertTrue(passed, findings)

    def test_grader_accepts_the_reported_split_work_profile_output(self) -> None:
        """Profile facts split across role and project name must satisfy this classification scenario."""
        scenario = get_memory_shadow_scenario("capture_explicit_work_background_as_profile_fact")
        operations = (
            {
                "operation": "add",
                "target_memory_id": None,
                "data_point_type": "profile_fact",
                "memory_basis": "stable_user_attribute",
                "category": "work",
                "key": "job_title",
                "label": "Job Title",
                "value": "Matchmaker",
                "confidence": 0.9,
                "evidence_message_indexes": [0],
            },
            {
                "operation": "add",
                "target_memory_id": None,
                "data_point_type": "profile_fact",
                "memory_basis": "stable_user_attribute",
                "category": "work",
                "key": "product_name",
                "label": "Product Name",
                "value": "Omiryn",
                "confidence": 0.9,
                "evidence_message_indexes": [0],
            },
        )

        passed, findings = grade_memory_shadow_result(
            scenario=scenario,
            decision="propose",
            operations=operations,
            structurally_valid=True,
        )

        self.assertTrue(passed, findings)

    def test_grader_rejects_matching_fact_for_explicit_work_background(self) -> None:
        """The flexible work scenario still forbids a matching-fact classification."""
        scenario = get_memory_shadow_scenario("capture_explicit_work_background_as_profile_fact")
        operation = {
            "operation": "add",
            "target_memory_id": None,
            "data_point_type": "matching_fact",
            "memory_basis": "explicit_matching_preference",
            "category": "work",
            "key": "product_builder",
            "label": "Builds a matchmaking product",
            "value": "Omiryn",
            "confidence": 0.9,
            "evidence_message_indexes": [0],
        }

        passed, findings = grade_memory_shadow_result(
            scenario=scenario,
            decision="propose",
            operations=(operation,),
            structurally_valid=True,
        )

        self.assertFalse(passed)
        self.assertIn("disallowed memory type", " ".join(findings))

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
            "memory_basis": "direct_chat_preference",
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

    def test_grader_rejects_short_lived_context_without_expiry_support(self) -> None:
        scenario = get_memory_shadow_scenario("ignore_short_lived_health_context_without_expiry")
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

        self.assertFalse(passed)

    def test_grader_accepts_distinct_optional_fact_but_still_rejects_duplicates(self) -> None:
        scenario = get_memory_shadow_scenario("capture_hinglish_partner_personality")
        required = {
            "operation": "add",
            "target_memory_id": None,
            "data_point_type": "matching_fact",
            "memory_basis": "explicit_matching_preference",
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
            "memory_basis": "explicit_matching_preference",
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
                    "memory_basis": "explicit_matching_preference",
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

    async def test_runner_fails_an_over_inferred_memory_from_semantic_judge(self) -> None:
        scenario = get_memory_shadow_scenario(
            "capture_explicit_work_background_as_profile_fact"
        )
        raw = {
            "decision": "propose",
            "operations": [
                {
                    "operation": "add",
                    "target_memory_id": None,
                    "data_point_type": "profile_fact",
                    "memory_basis": "stable_user_attribute",
                    "category": "work",
                    "key": "job_title",
                    "label": "Job title",
                    "value": "Matchmaker",
                    "confidence": 0.9,
                    "evidence_message_indexes": [0],
                }
            ],
            "thread_operation": {"operation": "none"},
            "handoff": {
                "summary": "The user builds Omiryn.",
                "active_people": [],
                "active_topics": ["work"],
                "unresolved_references": [],
            },
        }
        semantic_judge = AsyncMock()
        semantic_judge.judge_name = "Memory evidence judge test:model"
        semantic_judge.judge_memories.return_value = MemoryEvidenceJudgment(
            passed=False,
            operations=(
                MemoryOperationJudgment(
                    index=0,
                    supported=False,
                    issues=("unsupported_inference",),
                    reason="Building a product does not establish Matchmaker as a job title.",
                ),
            ),
            overall_reason="The proposed job title exceeds the cited evidence.",
        )

        with patch(
            "agent.evals.memory.runner.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=raw,
        ):
            result = await run_memory_shadow_scenario(
                scenario=scenario,
                model="memory-model",
                timeout_seconds=30,
                semantic_judge=semantic_judge,
            )

        self.assertFalse(result.passed)
        payload = scenario_result_payload(result, scenario=scenario)
        self.assertFalse(payload["observed"]["semantic_judgment"]["passed"])
        self.assertIn("unsupported_inference", " ".join(payload["findings"]))

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
                        "semantic_judgment": {
                            "judge_name": "Memory evidence judge deepinfra:judge-model",
                            "passed": False,
                            "operations": [
                                {
                                    "index": 0,
                                    "supported": False,
                                    "issues": ["unsupported_inference"],
                                    "reason": "The proposed title was not stated by the user.",
                                }
                            ],
                            "overall_reason": "The memory exceeds its cited evidence.",
                        },
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
        self.assertIn("Semantic evidence review", markdown)
        self.assertIn("Unsupported inference", markdown)
        self.assertIn("The proposed title was not stated by the user", markdown)
        self.assertIn("Memory shadow eval", history)
        self.assertIn("0%", history)


if __name__ == "__main__":
    unittest.main()
