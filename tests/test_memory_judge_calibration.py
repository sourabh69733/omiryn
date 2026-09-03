"""Tests calibration of the independent semantic memory judge."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agent.evals.behavior.reporting.live import TerminalProgressReporter
from agent.evals.behavior.reporting.writer import render_markdown_report
from agent.evals.memory.calibration import (
    MEMORY_JUDGE_CALIBRATION_CASES,
    MemoryJudgeCalibrationCase,
    MemoryJudgeExpectedVerdict,
    calibration_report_payload,
    run_memory_judge_calibration,
)
from agent.evals.memory.judge import MemoryEvidenceJudgment, MemoryOperationJudgment


class _KnownVerdictJudge:
    """Returns the verdict encoded by each synthetic calibration operation."""

    judge_name = "known-verdict-memory-judge"

    def __init__(self, cases=MEMORY_JUDGE_CALIBRATION_CASES) -> None:
        self._expected = {case.messages[0]["content"]: case.expected_verdicts for case in cases}
        self.conversation_ids: list[str] = []

    async def judge_memories(self, *, messages, operations, conversation_id):
        self.conversation_ids.append(conversation_id)
        expected = self._expected[messages[0]["content"]]
        judgments = tuple(
            MemoryOperationJudgment(
                index=index,
                supported=expected[index].supported,
                issues=expected[index].required_issues,
                reason="Known calibration verdict.",
            )
            for index, _operation in enumerate(operations)
        )
        return MemoryEvidenceJudgment(
            passed=all(item.supported for item in judgments),
            operations=judgments,
            overall_reason="Known calibration verdicts returned.",
        )


class MemoryJudgeCalibrationTest(unittest.IsolatedAsyncioTestCase):
    def test_catalogue_covers_positive_and_all_negative_issue_classes(self) -> None:
        expected = [
            verdict for case in MEMORY_JUDGE_CALIBRATION_CASES for verdict in case.expected_verdicts
        ]
        required_issues = {issue for verdict in expected for issue in verdict.required_issues}

        self.assertTrue(any(verdict.supported for verdict in expected))
        self.assertTrue(any(not verdict.supported for verdict in expected))
        self.assertEqual(
            required_issues,
            {
                "unsupported_inference",
                "wrong_memory_type",
                "distorted_meaning",
                "incidental_content",
                "over_broad",
            },
        )

    async def test_known_verdicts_pass_every_calibration_case(self) -> None:
        report = await run_memory_judge_calibration(_KnownVerdictJudge())

        self.assertTrue(report.passed)
        self.assertEqual(report.completed_cases, report.total_cases)
        self.assertEqual(report.false_accepts, 0)
        self.assertEqual(report.false_rejects, 0)
        self.assertEqual(report.issue_mismatches, 0)

        payload = calibration_report_payload(report)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["completed_cases"], len(MEMORY_JUDGE_CALIBRATION_CASES))
        self.assertEqual(
            payload["cases"][0]["evidence_messages"],
            ["I work as a civil engineer."],
        )
        self.assertEqual(payload["cases"][0]["proposed_operations"][0]["value"], "civil engineer")

    async def test_streams_readable_evidence_proposal_and_judge_verdict(self) -> None:
        stream = StringIO()
        reporter = TerminalProgressReporter(stream=stream)
        case = MEMORY_JUDGE_CALIBRATION_CASES[0]

        await run_memory_judge_calibration(
            _KnownVerdictJudge((case,)),
            cases=(case,),
            event_sink=reporter,
        )

        output = stream.getvalue()
        self.assertIn("Memory judge check 1/1: Accept explicit profile fact", output)
        self.assertIn("Evidence: I work as a civil engineer.", output)
        self.assertIn(
            "Proposed memory: profile_fact / Works as a civil engineer = 'civil engineer'",
            output,
        )
        self.assertIn("Judge verdict: supported; issues=none", output)
        self.assertIn("Expected: supported", output)
        self.assertIn("Result: PASS", output)

    async def test_registers_one_owned_conversation_for_all_usage_events(self) -> None:
        judge = _KnownVerdictJudge()

        with patch("agent.evals.memory.calibration.save_conversation") as save_conversation:
            await run_memory_judge_calibration(judge)

        save_conversation.assert_called_once()
        conversation, user_id = save_conversation.call_args.args
        self.assertEqual(conversation["id"], judge.conversation_ids[0])
        self.assertEqual(conversation["user_id"], user_id)
        self.assertEqual(set(judge.conversation_ids), {conversation["id"]})

    async def test_rejection_with_equivalent_issue_remains_a_diagnostic(self) -> None:
        case = MemoryJudgeCalibrationCase(
            id="wrong_reason",
            messages=({"role": "user", "content": "Explain decorators."},),
            operations=(
                {
                    "operation": "add",
                    "data_point_type": "profile_fact",
                    "label": "Likes decorators",
                    "value": "decorators",
                    "evidence_message_indexes": [0],
                },
            ),
            expected_verdicts=(
                MemoryJudgeExpectedVerdict(
                    supported=False,
                    required_issues=("incidental_content",),
                ),
            ),
        )

        judge = _KnownVerdictJudge((case,))
        judge._expected[case.messages[0]["content"]] = (
            MemoryJudgeExpectedVerdict(
                supported=False,
                required_issues=("unsupported_inference",),
            ),
        )
        report = await run_memory_judge_calibration(judge, cases=(case,))

        self.assertTrue(report.passed)
        self.assertEqual(report.issue_mismatches, 1)
        self.assertTrue(report.cases[0].passed)
        self.assertIsNone(report.cases[0].failure_reason)


class MemoryJudgeCalibrationReportingTest(unittest.TestCase):
    def test_readable_report_explains_failed_calibration_case(self) -> None:
        payload = {
            "stage": "memory_judge_calibration",
            "passed": False,
            "judges": ["Memory evidence judge mock:mock"],
            "run": {
                "finished_at": "2026-09-01T10:00:00+00:00",
                "duration_seconds": 1.0,
                "api_calls": 8,
            },
            "companion": {
                "agent_name": "Memory evidence judge calibration",
                "provider": "mock",
                "model": "mock",
                "prompt_version": "memory-judge-v1",
            },
            "judge_calibration": {
                "passed": False,
                "accuracy": 0.875,
                "false_accepts": 0,
                "false_rejects": 0,
                "issue_mismatches": 1,
                "judge_errors": 0,
                "completed_cases": 8,
                "total_cases": 8,
                "cases": [
                    {
                        "id": "reject_incidental_subject",
                        "passed": False,
                        "judge_error": None,
                        "failure_reason": ("Missing required issue category: incidental_content."),
                        "evidence_messages": ["Can you explain Python decorators?"],
                        "proposed_operations": [
                            {
                                "data_point_type": "profile_fact",
                                "label": "Likes Python",
                                "value": "Python",
                            }
                        ],
                        "operations": [
                            {
                                "expected_supported": False,
                                "observed_supported": False,
                                "required_issues": ["incidental_content"],
                                "observed_issues": ["unsupported_inference"],
                                "reason": (
                                    "The question does not establish a personal preference."
                                ),
                            }
                        ],
                    }
                ],
            },
        }

        markdown = render_markdown_report(payload)

        self.assertIn("# Background Memory Evaluation Report", markdown)
        self.assertIn("judge reliability check", markdown.casefold())
        self.assertIn("Can you explain Python decorators?", markdown)
        self.assertIn("Likes Python", markdown)
        self.assertIn("Expected: rejected", markdown)
        self.assertIn("Observed: rejected", markdown)
        self.assertIn("Incidental content", markdown)
        self.assertIn("The question does not establish a personal preference.", markdown)
        self.assertIn("Missing required issue category: incidental_content", markdown)
        self.assertIn("Do not trust", markdown)


class MemoryJudgeCalibrationCliTest(unittest.TestCase):
    def test_calibration_only_stops_before_memory_extraction(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(project_root / "scripts/evals/run_memory_evals.py"),
                    "--provider",
                    "mock",
                    "--judge-provider",
                    "mock",
                    "--calibration-only",
                    "--no-save",
                    "--quiet",
                ],
                cwd=project_root,
                env={
                    **os.environ,
                    "DATABASE_URL": f"sqlite:///{directory}/memory-calibration.db",
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Memory judge calibration: FAIL", result.stdout)
        self.assertNotIn("Memory shadow suite", result.stdout)


if __name__ == "__main__":
    unittest.main()
