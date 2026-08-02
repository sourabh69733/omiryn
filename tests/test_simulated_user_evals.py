from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.evals.behavior.events import EvalEvent
from agent.evals.behavior.live_reporter import LiveRunStats, TerminalProgressReporter
from agent.evals.behavior.report_writer import (
    attach_run_metadata,
    render_markdown_report,
    save_evaluation_reports,
)
from agent.evals.behavior.runtime_driver import RuntimeDriverConfig
from agent.evals.behavior.simulated_runner import (
    run_simulated_conversation,
    simulated_conversation_payload,
)
from agent.evals.behavior.simulated_user import (
    ProviderSimulatedUser,
    SimulatedUserDecision,
    SimulatedUserExecutionError,
    SimulatedUserProtocolError,
    SimulatedUserScenario,
    USER_EXPERIENCE_DIMENSIONS,
    UserExperienceGrade,
    UserExperienceVerdict,
    build_simulated_user_request,
    build_user_experience_judge_request,
    parse_simulated_user_decision,
    parse_user_experience_verdict,
)


def ai_user_scenario(*, minimum_turns: int = 2, maximum_turns: int = 4):
    return SimulatedUserScenario(
        id="dynamic_test",
        description="Test whether the companion can handle disagreement.",
        persona="A skeptical user who writes briefly and dislikes canned replies.",
        goal="Challenge the companion naturally and respond to what it says.",
        user_profile={"display_name": "Synthetic User"},
        minimum_turns=minimum_turns,
        maximum_turns=maximum_turns,
        mock_messages=("first", "second"),
    )


def user_verdict(*, passed: bool = True) -> UserExperienceVerdict:
    score = 3 if passed else 2
    return UserExperienceVerdict(
        passed=passed,
        average_score=float(score),
        would_continue=passed,
        grades=tuple(
            UserExperienceGrade(dimension, score, f"Evidence for {dimension}.")
            for dimension in USER_EXPERIENCE_DIMENSIONS
        ),
        overall_reason="It felt engaging." if passed else "It felt weak.",
        biggest_problem="none" if passed else "The replies felt generic.",
    )


def user_verdict_json(*, scores: dict[str, int] | None = None, would_continue=True) -> str:
    actual_scores = {dimension: 3 for dimension in USER_EXPERIENCE_DIMENSIONS}
    actual_scores.update(scores or {})
    return json.dumps(
        {
            "dimensions": [
                {"id": dimension, "score": actual_scores[dimension], "reason": "Evidence."}
                for dimension in USER_EXPERIENCE_DIMENSIONS
            ],
            "would_continue": would_continue,
            "overall_reason": "Honest summary.",
            "biggest_problem": "none",
        }
    )


class SequenceUser:
    def __init__(
        self,
        decisions: list[SimulatedUserDecision],
        verdict: UserExperienceVerdict | None = None,
    ) -> None:
        self.decisions = decisions
        self.verdict = verdict or user_verdict()
        self.transcripts: list[tuple[dict[str, str], ...]] = []
        self.judgment_transcripts: list[tuple[dict[str, str], ...]] = []

    async def next_turn(self, *, transcript, **_kwargs):
        self.transcripts.append(transcript)
        return self.decisions.pop(0)

    async def judge_conversation(self, *, transcript, **_kwargs):
        self.judgment_transcripts.append(transcript)
        return self.verdict


class SimulatedUserContractTest(unittest.IsolatedAsyncioTestCase):
    def test_scenario_rejects_impossible_turn_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "maximum_turns"):
            ai_user_scenario(minimum_turns=3, maximum_turns=2)

    def test_prompt_requests_natural_user_behavior_without_judging(self) -> None:
        prompt, payload = build_simulated_user_request(
            scenario=ai_user_scenario(),
            transcript=({"role": "assistant", "content": "What happened?"},),
            turn_index=1,
        )

        self.assertIn("one realistic human user", prompt)
        self.assertIn("Never evaluate, score", prompt)
        decoded = json.loads(payload)
        self.assertIn("skeptical user", decoded["scenario"]["persona"])
        self.assertTrue(decoded["finishing_allowed"])
        self.assertEqual(decoded["transcript"][0]["content"], "What happened?")

    def test_parser_accepts_message_and_allowed_finish(self) -> None:
        message = parse_simulated_user_decision(
            '{"action":"message","message":"Nahi, I disagree."}',
            allow_finish=False,
        )
        finished = parse_simulated_user_decision(
            '{"action":"finish","message":null}',
            allow_finish=True,
        )

        self.assertEqual(message.message, "Nahi, I disagree.")
        self.assertEqual(finished.action, "finish")

    def test_parser_rejects_premature_finish(self) -> None:
        with self.assertRaisesRegex(SimulatedUserProtocolError, "minimum_turns"):
            parse_simulated_user_decision(
                '{"action":"finish","message":null}',
                allow_finish=False,
            )

    def test_parser_rejects_malformed_or_empty_output(self) -> None:
        bad_values = (
            "not json",
            '{"action":"unknown","message":"hello"}',
            '{"action":"message","message":""}',
        )
        for raw in bad_values:
            with self.subTest(raw=raw), self.assertRaises(SimulatedUserProtocolError):
                parse_simulated_user_decision(raw, allow_finish=True)

    def test_user_judge_prompt_is_separate_and_contains_full_context(self) -> None:
        prompt, payload = build_user_experience_judge_request(
            scenario=ai_user_scenario(),
            transcript=(
                {"role": "user", "content": "You never disagree."},
                {"role": "assistant", "content": "I disagree with that."},
            ),
        )

        self.assertIn("stop generating chat messages and judge", prompt)
        self.assertIn("untrusted conversation data", prompt)
        self.assertNotIn('"action":"message"', prompt)
        decoded = json.loads(payload)
        self.assertEqual(decoded["required_dimensions"], list(USER_EXPERIENCE_DIMENSIONS))
        self.assertEqual(decoded["transcript"][-1]["role"], "assistant")

    def test_user_judge_parser_computes_pass_and_fail_deterministically(self) -> None:
        passing = parse_user_experience_verdict(user_verdict_json())
        low_dimension = parse_user_experience_verdict(user_verdict_json(scores={"naturalness": 2}))
        would_not_continue = parse_user_experience_verdict(user_verdict_json(would_continue=False))

        self.assertTrue(passing.passed)
        self.assertFalse(low_dimension.passed)
        self.assertFalse(would_not_continue.passed)
        self.assertAlmostEqual(low_dimension.average_score, 17 / 6, places=3)

    def test_user_judge_parser_rejects_invalid_schema(self) -> None:
        valid = json.loads(user_verdict_json())
        invalid_payloads = []
        missing = {**valid, "dimensions": valid["dimensions"][:-1]}
        invalid_payloads.append(missing)
        duplicate = {**valid, "dimensions": [*valid["dimensions"][:-1], valid["dimensions"][0]]}
        invalid_payloads.append(duplicate)
        boolean_score = json.loads(user_verdict_json())
        boolean_score["dimensions"][0]["score"] = True
        invalid_payloads.append(boolean_score)
        empty_reason = json.loads(user_verdict_json())
        empty_reason["dimensions"][0]["reason"] = ""
        invalid_payloads.append(empty_reason)
        invalid_payloads.append({**valid, "would_continue": "yes"})

        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(SimulatedUserProtocolError):
                parse_user_experience_verdict(json.dumps(payload))

    async def test_mock_user_has_deterministic_offline_sequence(self) -> None:
        user = ProviderSimulatedUser(provider="mock")
        scenario = ai_user_scenario()

        first = await user.next_turn(
            scenario=scenario,
            transcript=(),
            turn_index=0,
            conversation_id="conversation",
        )
        second = await user.next_turn(
            scenario=scenario,
            transcript=(),
            turn_index=1,
            conversation_id="conversation",
        )
        finished = await user.next_turn(
            scenario=scenario,
            transcript=(),
            turn_index=2,
            conversation_id="conversation",
        )

        self.assertEqual((first.message, second.message), ("first", "second"))
        self.assertEqual(finished.action, "finish")

        verdict = await user.judge_conversation(
            scenario=scenario,
            transcript=(),
            conversation_id="conversation",
        )
        self.assertFalse(verdict.passed)
        self.assertFalse(verdict.would_continue)

    async def test_provider_retries_timeout_and_emits_visible_events(self) -> None:
        calls = 0
        events: list[EvalEvent] = []

        async def provider_call(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TimeoutError("slow")
            return '{"action":"message","message":"Still not convinced."}'

        user = ProviderSimulatedUser(
            provider="deepinfra",
            model="user-model",
            max_attempts=2,
            retry_delay_seconds=0,
            event_sink=events.append,
        )
        with patch(
            "agent.evals.behavior.simulated_user._provider_call",
            return_value=provider_call,
        ):
            decision = await user.next_turn(
                scenario=ai_user_scenario(),
                transcript=(),
                turn_index=0,
                conversation_id="conversation",
            )

        self.assertEqual(calls, 2)
        self.assertEqual(decision.message, "Still not convinced.")
        self.assertEqual(
            [event.kind for event in events],
            [
                "simulated_user_call_started",
                "simulated_user_call_retry",
                "simulated_user_call_started",
                "simulated_user_call_completed",
            ],
        )

    async def test_provider_failure_fails_closed(self) -> None:
        async def provider_call(*_args, **_kwargs):
            raise RuntimeError("bad request")

        user = ProviderSimulatedUser(provider="deepinfra", max_attempts=3)
        with (
            patch(
                "agent.evals.behavior.simulated_user._provider_call",
                return_value=provider_call,
            ),
            self.assertRaisesRegex(SimulatedUserExecutionError, "1 attempts"),
        ):
            await user.next_turn(
                scenario=ai_user_scenario(),
                transcript=(),
                turn_index=0,
                conversation_id="conversation",
            )

    async def test_provider_repairs_non_json_user_message_once(self) -> None:
        responses = iter(
            (
                "Still not convinced.",
                '{"action":"message","message":"Still not convinced."}',
            )
        )
        calls = []

        async def provider_call(system_prompt, messages, **kwargs):
            calls.append((system_prompt, messages, kwargs))
            return next(responses)

        user = ProviderSimulatedUser(provider="deepinfra", model="user-model")
        with patch(
            "agent.evals.behavior.simulated_user._provider_call",
            return_value=provider_call,
        ):
            decision = await user.next_turn(
                scenario=ai_user_scenario(),
                transcript=(),
                turn_index=0,
                conversation_id="conversation",
            )

        self.assertEqual(decision.message, "Still not convinced.")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[1][2]["request_kind"],
            "behavior_eval_user_simulator_repair",
        )
        repair_data = json.loads(calls[1][1][0]["content"])
        self.assertEqual(repair_data["malformed_response"], "Still not convinced.")
        self.assertFalse(repair_data["finishing_allowed"])

    async def test_provider_fails_closed_after_bad_user_message_repair(self) -> None:
        calls = 0

        async def provider_call(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return "still not json"

        user = ProviderSimulatedUser(provider="deepinfra")
        with (
            patch(
                "agent.evals.behavior.simulated_user._provider_call",
                return_value=provider_call,
            ),
            self.assertRaises(SimulatedUserProtocolError),
        ):
            await user.next_turn(
                scenario=ai_user_scenario(),
                transcript=(),
                turn_index=0,
                conversation_id="conversation",
            )

        self.assertEqual(calls, 2)

    async def test_user_judgment_uses_same_provider_model_and_judge_request_kind(self) -> None:
        calls = []

        async def provider_call(*args, **kwargs):
            calls.append((args, kwargs))
            return user_verdict_json()

        user = ProviderSimulatedUser(provider="deepinfra", model="same-user-model")
        with patch(
            "agent.evals.behavior.simulated_user._provider_call",
            return_value=provider_call,
        ):
            verdict = await user.judge_conversation(
                scenario=ai_user_scenario(),
                transcript=({"role": "user", "content": "hello"},),
                conversation_id="conversation",
            )

        self.assertTrue(verdict.passed)
        self.assertEqual(calls[0][1]["model"], "same-user-model")
        self.assertEqual(calls[0][1]["temperature"], 0.0)
        self.assertEqual(calls[0][1]["request_kind"], "behavior_eval_user_judge")

    async def test_provider_repairs_malformed_user_judgment_once(self) -> None:
        responses = iter(("I would continue, 3 out of 4.", user_verdict_json()))
        calls = []

        async def provider_call(system_prompt, messages, **kwargs):
            calls.append((system_prompt, messages, kwargs))
            return next(responses)

        user = ProviderSimulatedUser(provider="deepinfra", model="same-user-model")
        with patch(
            "agent.evals.behavior.simulated_user._provider_call",
            return_value=provider_call,
        ):
            verdict = await user.judge_conversation(
                scenario=ai_user_scenario(),
                transcript=({"role": "user", "content": "hello"},),
                conversation_id="conversation",
            )

        self.assertTrue(verdict.passed)
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[1][2]["request_kind"],
            "behavior_eval_user_judge_repair",
        )
        repair_data = json.loads(calls[1][1][0]["content"])
        self.assertEqual(repair_data["required_dimensions"], list(USER_EXPERIENCE_DIMENSIONS))
        self.assertIn("do not improve", calls[1][0])


class SimulatedConversationRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_runner_alternates_using_the_growing_transcript(self) -> None:
        user = SequenceUser(
            [
                SimulatedUserDecision("message", "You always agree."),
                SimulatedUserDecision("message", "That reply felt generic."),
                SimulatedUserDecision("finish"),
            ]
        )
        replies = iter(("I don't agree with that.", "Fair criticism; that was generic."))

        async def fake_agent_turn(*, messages, user_text, **_kwargs):
            return SimpleNamespace(
                messages=[
                    *messages,
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": next(replies)},
                ]
            )

        events: list[EvalEvent] = []
        with (
            patch("agent.evals.behavior.simulated_runner.save_conversation"),
            patch("agent.evals.behavior.simulated_runner.list_agent_traces", return_value=[]),
            patch(
                "agent.evals.behavior.simulated_runner.list_agent_context_snapshots",
                return_value=[],
            ),
            patch(
                "agent.evals.behavior.simulated_runner.run_agent_turn",
                side_effect=fake_agent_turn,
            ),
        ):
            result = await run_simulated_conversation(
                scenario=ai_user_scenario(),
                simulated_user=user,
                companion=RuntimeDriverConfig(provider="mock", model="mock"),
                event_sink=events.append,
            )

        self.assertEqual(len(result.turns), 2)
        self.assertEqual(result.stop_reason, "ai_user_finished")
        self.assertEqual(user.transcripts[0], ())
        self.assertEqual(
            [item["role"] for item in user.transcripts[1]],
            ["user", "assistant"],
        )
        self.assertEqual(
            user.transcripts[1][1]["content"],
            "I don't agree with that.",
        )
        self.assertEqual(
            [item["role"] for item in user.judgment_transcripts[0]],
            ["user", "assistant", "user", "assistant"],
        )
        self.assertTrue(result.user_verdict.passed)
        event_kinds = [event.kind for event in events]
        self.assertLess(
            event_kinds.index("user_judgment_started"), event_kinds.index("user_judgment_completed")
        )
        self.assertIn("simulated_conversation_completed", [event.kind for event in events])

    async def test_runner_stops_at_maximum_turns(self) -> None:
        user = SequenceUser(
            [SimulatedUserDecision("message", f"message {index}") for index in range(2)]
        )

        async def fake_agent_turn(*, messages, user_text, **_kwargs):
            return SimpleNamespace(
                messages=[
                    *messages,
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": "reply"},
                ]
            )

        with (
            patch("agent.evals.behavior.simulated_runner.save_conversation"),
            patch("agent.evals.behavior.simulated_runner.list_agent_traces", return_value=[]),
            patch(
                "agent.evals.behavior.simulated_runner.list_agent_context_snapshots",
                return_value=[],
            ),
            patch(
                "agent.evals.behavior.simulated_runner.run_agent_turn",
                side_effect=fake_agent_turn,
            ),
        ):
            result = await run_simulated_conversation(
                scenario=ai_user_scenario(minimum_turns=1, maximum_turns=2),
                simulated_user=user,
                companion=RuntimeDriverConfig(provider="mock", model="mock"),
            )

        self.assertEqual(len(result.turns), 2)
        self.assertEqual(result.stop_reason, "maximum_turns")


class SimulatedConversationReportTest(unittest.TestCase):
    def _payload(self) -> dict:
        result = SimpleNamespace(
            scenario_id="dynamic_test",
            stop_reason="ai_user_finished",
            user_verdict=user_verdict(passed=False),
            turns=(
                SimpleNamespace(
                    turn_index=0,
                    user_message="You always agree.",
                    assistant_reply="No, I don't think that is fair.",
                ),
            ),
        )
        payload = simulated_conversation_payload(
            result,
            simulated_user_provider="deepinfra",
            simulated_user_model="user-model",
        )
        attach_run_metadata(
            payload,
            stats=LiveRunStats(
                started_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                finished_at=datetime(2026, 8, 1, 0, 1, tzinfo=timezone.utc),
                duration_seconds=60,
                api_calls=2,
            ),
            companion_provider="deepinfra",
            companion_model="companion-model",
            prompt_version="v3",
            companion_agent_name="Mira",
        )
        return payload

    def test_markdown_shows_user_verdict_and_pending_independent_judge(self) -> None:
        markdown = render_markdown_report(self._payload())

        self.assertIn("**Result:** PENDING INDEPENDENT JUDGE", markdown)
        self.assertIn("**Companion agent:** Mira", markdown)
        self.assertIn("**Companion provider:** deepinfra", markdown)
        self.assertIn("**Companion model:** companion-model", markdown)
        self.assertIn("**AI User:** You always agree.", markdown)
        self.assertIn("**Companion:** No, I don't think that is fair.", markdown)
        self.assertIn("**User verdict:** FAIL", markdown)
        self.assertIn("**Average score:** 2.0/4", markdown)
        self.assertIn("The replies felt generic.", markdown)
        self.assertIn("AI user judge (deepinfra / user-model)", markdown)
        self.assertNotIn("## Judge reliability check", markdown)

    def test_saved_report_and_history_preserve_pending_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = save_evaluation_reports(
                self._payload(),
                output_dir=Path(directory),
                now=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )

            self.assertIn("PENDING INDEPENDENT JUDGE", paths.markdown.read_text(encoding="utf-8"))
            self.assertIn(
                "| PENDING INDEPENDENT JUDGE |",
                paths.history.read_text(encoding="utf-8"),
            )
            self.assertEqual(paths.markdown.parent.name, "2026-08-01")
            self.assertIn("## 2026-08-01", paths.history.read_text(encoding="utf-8"))
            self.assertIn("| 2.0/4 |", paths.history.read_text(encoding="utf-8"))
            self.assertIsNone(json.loads(paths.json.read_text(encoding="utf-8"))["passed"])

    def test_history_groups_multiple_runs_under_their_day(self) -> None:
        day_one = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
        day_two_first = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
        day_two_second = datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            for timestamp in (day_one, day_two_first, day_two_second):
                payload = self._payload()
                payload["run"]["finished_at"] = timestamp.isoformat()
                save_evaluation_reports(
                    payload,
                    output_dir=Path(directory),
                    now=timestamp,
                )

            history = (Path(directory) / "HISTORY.md").read_text(encoding="utf-8")

        self.assertEqual(history.count("## 2026-08-01"), 1)
        self.assertEqual(history.count("## 2026-08-02"), 1)
        self.assertEqual(history.count("| PENDING INDEPENDENT JUDGE |"), 3)
        self.assertNotIn("Open report", history)

    def test_terminal_distinguishes_conversation_and_user_judgment(self) -> None:
        stream = StringIO()
        reporter = TerminalProgressReporter(stream=stream)
        reporter(
            EvalEvent(
                kind="simulated_user_call_started",
                message="started",
                data={
                    "model_name": "user-model",
                    "attempt": 1,
                    "max_attempts": 3,
                    "purpose": "conversation",
                },
            )
        )
        reporter(
            EvalEvent(
                kind="simulated_user_call_started",
                message="started",
                data={
                    "model_name": "user-model",
                    "attempt": 1,
                    "max_attempts": 3,
                    "purpose": "judgment",
                },
            )
        )
        reporter(
            EvalEvent(
                kind="user_judgment_completed",
                message="done",
                data={
                    "passed": False,
                    "average_score": 2.0,
                    "would_continue": False,
                    "dimensions": [],
                },
            )
        )
        reporter(
            EvalEvent(
                kind="simulated_conversation_completed",
                message="done",
                data={"turn_count": 3, "stop_reason": "ai_user_finished"},
            )
        )

        self.assertIn("AI User (user-model) is thinking", stream.getvalue())
        self.assertIn("is judging the conversation", stream.getvalue())
        self.assertIn("AI-user verdict: FAIL", stream.getvalue())
        self.assertIn("PENDING independent judge", stream.getvalue())
        self.assertEqual(reporter.api_calls, 2)


class SimulatedConversationCliTest(unittest.TestCase):
    def _run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        project_root = Path(__file__).resolve().parents[1]
        environment = {
            **os.environ,
            "DATABASE_URL": f"sqlite:///{tempfile.gettempdir()}/omiryn-ai-user-cli.db",
        }
        return subprocess.run(
            [
                sys.executable,
                str(project_root / "scripts/evals/run_simulated_conversation.py"),
                "--provider",
                "mock",
                "--user-provider",
                "mock",
                *arguments,
            ],
            cwd=project_root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_cli_runs_offline_and_reports_user_verdict(self) -> None:
        result = self._run_cli("--no-save")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("user verdict FAIL", result.stdout)
        self.assertIn("overall PENDING independent judge", result.stdout)
        self.assertIn("AI-user scenario", result.stderr)
        self.assertIn("AI User:", result.stderr)

    def test_cli_saves_to_requested_report_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run_cli("--quiet", "--output-dir", directory)

            self.assertEqual(result.returncode, 0, result.stderr)
            day_directories = [path for path in Path(directory).iterdir() if path.is_dir()]
            self.assertEqual(len(day_directories), 1)
            self.assertTrue(list(day_directories[0].glob("*.md")))
            self.assertTrue(list(day_directories[0].glob("*.json")))
            self.assertTrue((Path(directory) / "HISTORY.md").exists())


if __name__ == "__main__":
    unittest.main()
