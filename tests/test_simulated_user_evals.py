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
    build_simulated_user_request,
    parse_simulated_user_decision,
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


class SequenceUser:
    def __init__(self, decisions: list[SimulatedUserDecision]) -> None:
        self.decisions = decisions
        self.transcripts: list[tuple[dict[str, str], ...]] = []

    async def next_turn(self, *, transcript, **_kwargs):
        self.transcripts.append(transcript)
        return self.decisions.pop(0)


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

    def test_markdown_is_explicitly_unscored_and_understandable(self) -> None:
        markdown = render_markdown_report(self._payload())

        self.assertIn("**Result:** UNSCORED", markdown)
        self.assertIn("**Companion agent:** Mira", markdown)
        self.assertIn("**Companion provider:** deepinfra", markdown)
        self.assertIn("**Companion model:** companion-model", markdown)
        self.assertIn("**AI User:** You always agree.", markdown)
        self.assertIn("**Companion:** No, I don't think that is fair.", markdown)
        self.assertIn("No quality verdict", markdown)
        self.assertNotIn("## Judge reliability check", markdown)

    def test_saved_report_and_history_preserve_unscored_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = save_evaluation_reports(
                self._payload(),
                output_dir=Path(directory),
                now=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )

            self.assertIn("UNSCORED", paths.markdown.read_text(encoding="utf-8"))
            self.assertIn("| UNSCORED |", paths.history.read_text(encoding="utf-8"))
            self.assertIsNone(json.loads(paths.json.read_text(encoding="utf-8"))["passed"])

    def test_terminal_distinguishes_ai_user_and_unscored_result(self) -> None:
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
        self.assertIn("UNSCORED", stream.getvalue())
        self.assertEqual(reporter.api_calls, 1)


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

    def test_cli_runs_offline_and_reports_unscored(self) -> None:
        result = self._run_cli("--no-save")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AI-user conversation captured: 3 turns, UNSCORED", result.stdout)
        self.assertIn("AI-user scenario", result.stderr)
        self.assertIn("AI User:", result.stderr)

    def test_cli_saves_to_requested_report_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run_cli("--quiet", "--output-dir", directory)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(list(Path(directory).glob("*.md")))
            self.assertTrue(list(Path(directory).glob("*.json")))
            self.assertTrue((Path(directory) / "HISTORY.md").exists())


if __name__ == "__main__":
    unittest.main()
