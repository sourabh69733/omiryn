"""Protects the real-model evaluator for the canonical v3 memory contract."""

from __future__ import annotations

import unittest
from argparse import Namespace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from agent.evals.behavior.core.events import EvalEvent
from agent.evals.behavior.reporting.live import TerminalProgressReporter
from agent.evals.behavior.reporting.writer import save_evaluation_reports
from agent.evals.memory.judge import build_memory_evidence_judge_request
from agent.evals.memory.v3.runner import (
    grade_memory_v3_result,
    run_memory_v3_scenario,
    scenario_result_payload,
)
from agent.evals.memory.v3.scenarios import (
    MEMORY_V3_SCENARIOS,
    get_memory_v3_scenario,
    list_memory_v3_scenarios,
)
from storage import reset_db


class MemoryV3EvaluationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()

    def test_catalogue_covers_v3_taxonomy_lifecycle_and_safety(self) -> None:
        tags = {tag for scenario in MEMORY_V3_SCENARIOS for tag in scenario.tags}

        self.assertTrue(
            {
                "semantic",
                "episodic",
                "relationship",
                "procedural",
                "profile",
                "matching",
                "personalization",
                "reinforce",
                "supersede",
                "retract",
                "assistant_contamination",
                "cross_batch",
                "incidental_content",
                "sensitivity",
            }.issubset(tags)
        )
        self.assertGreaterEqual(len(MEMORY_V3_SCENARIOS), 12)
        self.assertEqual(
            len({scenario.id for scenario in MEMORY_V3_SCENARIOS}),
            len(MEMORY_V3_SCENARIOS),
        )

    def test_catalogue_covers_memory_admission_boundaries(self) -> None:
        scenario_ids = {scenario.id for scenario in MEMORY_V3_SCENARIOS}

        self.assertTrue(
            {
                "ignore_quoted_third_party_preference",
                "ignore_hypothetical_self_description",
                "ignore_transient_task_content",
                "ignore_ambiguous_acknowledgement",
                "capture_explicit_durable_preference",
            }.issubset(scenario_ids)
        )
        admission_cases = list_memory_v3_scenarios(tags=("admission_quality",))
        self.assertGreaterEqual(len(admission_cases), 5)
        self.assertGreaterEqual(
            sum(case.expected_decision == "no_change" for case in admission_cases),
            4,
        )
        self.assertTrue(any(case.expected_operations for case in admission_cases))

    def test_lookup_and_filter_use_only_v3_scenarios(self) -> None:
        lifecycle = list_memory_v3_scenarios(tags=("lifecycle",))

        self.assertEqual(
            {scenario.id for scenario in lifecycle},
            {
                "explicitly_renew_retracted_preference",
                "ignore_incidental_repeat_of_retracted_memory",
                "reinforce_existing_preference_without_duplicate",
                "supersede_corrected_location",
                "retract_withdrawn_preference",
            },
        )
        self.assertEqual(
            get_memory_v3_scenario("capture_lived_trip_as_episode")
            .expected_operations[0]
            .memory_kind,
            "episodic",
        )
        with self.assertRaisesRegex(ValueError, "Unknown v3 memory scenario"):
            get_memory_v3_scenario("missing")

    def test_retracted_fixture_is_history_not_a_lifecycle_target(self) -> None:
        scenario = get_memory_v3_scenario("ignore_incidental_repeat_of_retracted_memory")

        context = scenario.existing_memories[0].as_context()

        self.assertEqual(context["status"], "retracted")
        self.assertFalse(context["targetable"])

    async def test_runner_rejects_operations_targeting_inactive_history(self) -> None:
        scenario = get_memory_v3_scenario("ignore_incidental_repeat_of_retracted_memory")
        raw = {
            "decision": "propose",
            "operations": [
                {
                    "operation": "reinforce",
                    "target_memory_id": "retracted-weekend-memory",
                    "confidence": 0.9,
                    "importance": 0.7,
                    "evidence_message_indexes": [0],
                }
            ],
            "thread_operation": {"operation": "none"},
            "handoff": {
                "summary": "",
                "active_people": [],
                "active_topics": [],
                "unresolved_references": [],
            },
        }
        with patch(
            "agent.evals.memory.v3.runner.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=raw,
        ):
            result = await run_memory_v3_scenario(
                scenario=scenario,
                model="memory-model",
                timeout_seconds=30,
            )

        self.assertFalse(result.structurally_valid)
        self.assertIn("supplied active memory", " ".join(result.validation_errors))

    def test_grader_accepts_semantic_wording_but_requires_kind_purpose_and_evidence(self) -> None:
        scenario = get_memory_v3_scenario("capture_partner_location_preference")
        operation = {
            "operation": "add",
            "target_memory_id": None,
            "memory_kind": "semantic",
            "purposes": ["matching"],
            "key": "preferred_partner_location",
            "value": {"state": "Tamil Nadu", "near": "Chennai"},
            "sensitivity": "standard",
            "confidence": 0.94,
            "importance": 0.85,
            "evidence_message_indexes": [0],
        }

        passed, findings = grade_memory_v3_result(
            scenario=scenario,
            decision="propose",
            operations=(operation,),
            structurally_valid=True,
        )

        self.assertTrue(passed, findings)

        wrong = dict(operation, memory_kind="relationship", purposes=["personalization"])
        passed, findings = grade_memory_v3_result(
            scenario=scenario,
            decision="propose",
            operations=(wrong,),
            structurally_valid=True,
        )

        self.assertFalse(passed)
        self.assertIn("Missing expected operation", " ".join(findings))

        overclassified = dict(operation, purposes=["matching", "profile"])
        passed, findings = grade_memory_v3_result(
            scenario=scenario,
            decision="propose",
            operations=(overclassified,),
            structurally_valid=True,
        )
        self.assertFalse(passed)
        self.assertIn("Missing expected operation", " ".join(findings))

    def test_grader_rejects_unexpected_memory_for_incidental_content(self) -> None:
        scenario = get_memory_v3_scenario("ignore_incidental_technical_subject")
        operation = {
            "operation": "add",
            "memory_kind": "semantic",
            "purposes": ["profile"],
            "key": "favorite_language",
            "value": "Python",
            "sensitivity": "standard",
            "confidence": 0.8,
            "importance": 0.5,
            "evidence_message_indexes": [0],
        }

        passed, findings = grade_memory_v3_result(
            scenario=scenario,
            decision="propose",
            operations=(operation,),
            structurally_valid=True,
        )

        self.assertFalse(passed)
        self.assertIn("Unexpected operation", " ".join(findings))

    def test_vibe_grading_fails_ungrounded_lines_and_missing_ones(self) -> None:
        small_talk = get_memory_v3_scenario("vibe_small_talk_fills_nothing")
        showed = get_memory_v3_scenario("vibe_only_what_the_user_showed")

        def grade(scenario, vibe):
            return grade_memory_v3_result(
                scenario=scenario, decision="no_change", operations=(), structurally_valid=True, vibe=vibe
            )

        self.assertTrue(grade(small_talk, {})[0])
        passed, findings = grade(small_talk, {"humor": "Likes jokes."})
        self.assertFalse(passed)
        self.assertIn("did not show: humor", " ".join(findings))

        self.assertTrue(grade(showed, {"humor": "Needs someone who gets sarcasm."})[0])
        passed, findings = grade(showed, {"values": "Thinks loyalty is everything."})
        self.assertFalse(passed)
        self.assertIn("did not show: values", " ".join(findings))
        self.assertIn("Expected a vibe line for humor", " ".join(findings))

    async def test_runner_uses_v3_provider_and_validator_contract(self) -> None:
        scenario = get_memory_v3_scenario("capture_lived_trip_as_episode")
        raw = {
            "decision": "propose",
            "operations": [
                {
                    "operation": "add",
                    "memory_kind": "episodic",
                    "purposes": ["personalization"],
                    "key": "bengaluru_trip",
                    "value": "Visited Bengaluru for a college reunion",
                    "sensitivity": "standard",
                    "confidence": 0.9,
                    "importance": 0.7,
                    "occurred_at": None,
                    "valid_from": None,
                    "valid_until": None,
                    "evidence_message_indexes": [0],
                }
            ],
            "thread_operation": {"operation": "none"},
            "handoff": {
                "summary": "The user recalled a Bengaluru reunion trip.",
                "active_people": [],
                "active_topics": ["travel stories"],
                "unresolved_references": [],
            },
        }
        with patch(
            "agent.evals.memory.v3.runner.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=raw,
        ) as analyze:
            result = await run_memory_v3_scenario(
                scenario=scenario,
                model="memory-model",
                timeout_seconds=30,
            )

        self.assertTrue(result.passed, result.findings)
        self.assertEqual(analyze.await_args.kwargs["memory_version"], 3)
        payload = scenario_result_payload(result, scenario=scenario)
        self.assertEqual(payload["observed"]["operations"][0]["memory_kind"], "episodic")
        self.assertEqual(payload["observed"]["operations"][0]["purposes"], ["personalization"])

    def test_v3_evidence_judge_understands_kind_purpose_and_sensitivity(self) -> None:
        system_prompt, payload = build_memory_evidence_judge_request(
            messages=({"role": "user", "content": "I have a severe peanut allergy."},),
            operations=(
                {
                    "operation": "add",
                    "memory_kind": "semantic",
                    "purposes": ["profile"],
                    "key": "peanut_allergy",
                    "value": "severe",
                    "sensitivity": "highly_sensitive",
                    "evidence_message_indexes": [0],
                },
            ),
            memory_version=3,
        )
        for memory_kind in ("semantic", "episodic", "relationship", "procedural"):
            self.assertIn(memory_kind, system_prompt)
        for purpose in ("profile", "matching", "personalization"):
            self.assertIn(purpose, system_prompt)
        self.assertIn("sensitivity", system_prompt)
        self.assertIn("wrong_sensitivity", system_prompt)
        self.assertIn("peanut_allergy", payload)

    def test_command_selects_v3_catalogue_from_pipeline_version(self) -> None:
        from scripts.evals.run_memory_evals import _evaluation_contract, _selected_scenarios

        args = Namespace(scenario_ids=["capture_lived_trip_as_episode"], scenario_tags=None)
        with patch.dict("os.environ", {"AGENT_PIPELINE_VERSION": "v3"}, clear=False):
            contract = _evaluation_contract()
            scenarios = _selected_scenarios(args, contract=contract)

        self.assertEqual(contract.memory_version, 3)
        self.assertEqual(contract.stage, "memory_v3_eval")
        self.assertEqual(scenarios[0].id, "capture_lived_trip_as_episode")

    def test_live_calibration_output_names_v3_memory_kind(self) -> None:
        stream = StringIO()
        reporter = TerminalProgressReporter(stream=stream)
        reporter(
            EvalEvent(
                kind="memory_judge_calibration_case_started",
                message="started",
                data={
                    "case_number": 1,
                    "total_cases": 1,
                    "case_id": "accept_v3_episode",
                    "evidence_messages": ["I visited Bengaluru."],
                    "operations": [
                        {
                            "memory_kind": "episodic",
                            "purposes": ["personalization"],
                            "key": "bengaluru_trip",
                            "value": "Visited Bengaluru",
                        }
                    ],
                },
            )
        )

        output = stream.getvalue()
        self.assertIn("episodic", output)
        self.assertIn("personalization", output)
        self.assertIn("bengaluru_trip", output)

    def test_v3_report_uses_canonical_memory_language(self) -> None:
        payload = {
            "stage": "memory_v3_eval",
            "passed": True,
            "judges": ["deterministic v3 expectation"],
            "judge_calibration": None,
            "run": {
                "finished_at": "2026-09-02T10:00:00+00:00",
                "duration_seconds": 1.0,
                "api_calls": 1,
            },
            "companion": {
                "agent_name": "V3 background cognition",
                "provider": "deepinfra",
                "model": "example-model",
                "prompt_version": "memory-v3",
            },
            "summary": {
                "total": 1,
                "passed": 1,
                "failed": 0,
                "structural_failures": 0,
                "live_memory_writes": False,
            },
            "scenarios": [
                {
                    "scenario_id": "capture_lived_trip_as_episode",
                    "description": "Capture a lived trip.",
                    "passed": True,
                    "input": {
                        "messages": [
                            {"role": "user", "content": "I visited Bengaluru for a reunion."}
                        ],
                        "processed_through_message_index": -1,
                        "existing_memories": [],
                    },
                    "expected": {
                        "decision": "propose",
                        "operations": [
                            {
                                "operation": "add",
                                "memory_kind": "episodic",
                                "required_purposes": ["personalization"],
                                "value_concepts": ["bengaluru"],
                                "evidence_message_indexes": [0],
                                "sensitivity": "standard",
                            }
                        ],
                    },
                    "observed": {
                        "decision": "propose",
                        "structurally_valid": True,
                        "duration_seconds": 1.0,
                        "validation_errors": [],
                        "operations": [
                            {
                                "operation": "add",
                                "memory_kind": "episodic",
                                "purposes": ["personalization"],
                                "key": "bengaluru_trip",
                                "value": "College reunion in Bengaluru",
                                "sensitivity": "standard",
                                "evidence_message_indexes": [0],
                            }
                        ],
                    },
                    "findings": ["V3 memory behavior matched the expected result."],
                }
            ],
        }
        with TemporaryDirectory() as directory:
            paths = save_evaluation_reports(payload, output_dir=Path(directory))
            markdown = paths.markdown.read_text(encoding="utf-8")

        self.assertIn("Canonical V3 Memory Evaluation Report", markdown)
        self.assertIn("episodic", markdown)
        self.assertIn("personalization", markdown)
        self.assertNotIn("profile_fact", markdown)


if __name__ == "__main__":
    unittest.main()
