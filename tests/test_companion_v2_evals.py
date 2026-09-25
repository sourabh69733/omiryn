"""Deterministic checks for the companion_v2 eval additions (no real model calls)."""

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent.evals.behavior.core.graders import hard_rule_findings
from agent.evals.behavior.core.models import (
    BehaviorScenario,
    ObservedTurn,
    ScenarioTurn,
    TurnExpectation,
)
from agent.evals.behavior.core.scenarios_v2 import COMPANION_V2_SCENARIOS
from agent.evals.behavior.judging.judge import build_judge_request
from agent.evals.behavior.reporting.writer import _scenario_markdown
from agent.evals.behavior.runner import BehaviorEvalConfig, report_payload, run_behavior_evals
from agent.evals.behavior.simulation.runtime import RuntimeDriverConfig, RuntimeScenarioDriver
from storage import get_conversation, get_user_timezone, reset_db

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "evals"


def _observed(reply: str, *, bubbles: tuple[str, ...] = (), turn_index: int = 0) -> ObservedTurn:
    return ObservedTurn(
        turn_index=turn_index,
        user_message="hi",
        assistant_reply=reply,
        assistant_messages=bubbles or (reply,),
    )


def _findings(expectation: TurnExpectation, observed: ObservedTurn, prior=()) -> set[str]:
    turn = ScenarioTurn(user_message="hi", expectation=expectation)
    return {finding.code for finding in hard_rule_findings(turn, observed, tuple(prior))}


class NewExpectationTest(unittest.TestCase):
    def test_bubble_limits(self) -> None:
        story = TurnExpectation(minimum_bubbles=3, maximum_bubbles=7, maximum_questions=None)
        self.assertIn("bubble_count", _findings(story, _observed("once", bubbles=("once", "upon"))))
        self.assertNotIn("bubble_count", _findings(story, _observed("a b c", bubbles=("a", "b", "c"))))

    def test_stock_phrase(self) -> None:
        expectation = TurnExpectation(forbid_stock_phrases=True)
        self.assertIn("stock_phrase", _findings(expectation, _observed("That sounds like fun!")))
        self.assertNotIn("stock_phrase", _findings(expectation, _observed("pineapple on pizza, bold")))

    def test_question_reply_ratio_counts_the_whole_conversation(self) -> None:
        expectation = TurnExpectation(maximum_question_reply_ratio=0.5)
        prior = [_observed("which one?"), _observed("was it good?")]
        self.assertIn(
            "too_many_question_replies", _findings(expectation, _observed("nice pick"), prior)
        )
        prior = [_observed("which one?"), _observed("nice")]
        self.assertNotIn(
            "too_many_question_replies", _findings(expectation, _observed("fair enough"), prior)
        )

    def test_question_streak(self) -> None:
        expectation = TurnExpectation(maximum_question_streak=2)
        asked = [_observed("which one?"), _observed("was it good?")]
        self.assertIn("question_streak", _findings(expectation, _observed("why?"), asked))
        self.assertNotIn("question_streak", _findings(expectation, _observed("fair"), asked))
        self.assertNotIn(
            "question_streak", _findings(expectation, _observed("why?"), [_observed("ok"), asked[0]])
        )

    def test_invalid_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TurnExpectation(minimum_bubbles=3, maximum_bubbles=2)
        with self.assertRaises(ValueError):
            TurnExpectation(maximum_question_reply_ratio=1.5)
        with self.assertRaises(ValueError):
            BehaviorScenario(
                id="x",
                description="x",
                turns=(ScenarioTurn("hi", TurnExpectation()),),
                start_at="2026-09-14T20:00:00",
            )


class TimedRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    async def test_turns_run_on_the_scenario_clock_with_background_first(self) -> None:
        scenario = BehaviorScenario(
            id="timed",
            description="timed run",
            start_at="2026-09-14T20:00:00+05:30",
            timezone="Asia/Kolkata",
            initial_messages=({"role": "assistant", "content": "hey"},),
            turns=(
                ScenarioTurn("I have an interview on Friday", TurnExpectation()),
                ScenarioTurn(
                    "when did I tell you?",
                    TurnExpectation(),
                    after_minutes=2 * 24 * 60,
                    run_background_before=True,
                ),
            ),
        )
        driver = RuntimeScenarioDriver(
            RuntimeDriverConfig(provider="mock", model="mock", pipeline_version="v3")
        )
        pending = iter([True, False])  # one batch waiting, then done
        with (
            patch(
                "agent.evals.behavior.simulation.runtime.has_pending_background_cognition",
                new=lambda *_args: next(pending, False),
            ),
            patch(
                "agent.evals.behavior.simulation.runtime.run_background_cognition",
                new=AsyncMock(return_value={"status": "live_applied"}),
            ) as background,
        ):
            turns = await driver.run_sample(scenario, 0)

        self.assertEqual([turn.sent_at for turn in turns], ["Mon 14 Sep, 8:01 pm", "Wed 16 Sep, 8:01 pm"])
        background.assert_awaited_once()
        user_id, conversation_id = turns[0].user_id, turns[0].conversation_id
        self.assertEqual(get_user_timezone(user_id), "Asia/Kolkata")
        stamps = [m["created_at"] for m in get_conversation(conversation_id, user_id)["messages"]]
        self.assertTrue(stamps[0].startswith("2026-09-14T14:30"))  # 8:00 pm IST in UTC
        self.assertTrue(stamps[-1].startswith("2026-09-16T14:31"))  # 8:01 pm IST in UTC

    def test_judge_sees_send_times(self) -> None:
        turn = ScenarioTurn("hi", TurnExpectation())
        observed = ObservedTurn(
            turn_index=0, user_message="hi", assistant_reply="hey", sent_at="Mon 14 Sep, 8:01 pm"
        )
        scenario = BehaviorScenario(id="s", description="d", turns=(turn,))
        _system, payload = build_judge_request(
            scenario=scenario, turn=turn, observed=observed, transcript=(observed,)
        )
        self.assertIn('"sent_at": "Mon 14 Sep, 8:01 pm"', payload)

    def test_judge_sees_each_bubble_on_its_own_line(self) -> None:
        turn = ScenarioTurn("tell me a story", TurnExpectation())
        observed = ObservedTurn(
            turn_index=0,
            user_message="tell me a story",
            assistant_reply="once upon a time there was Raju",
            assistant_messages=("once upon a time", "there was Raju"),
        )
        scenario = BehaviorScenario(id="s", description="d", turns=(turn,))
        system, payload = build_judge_request(
            scenario=scenario, turn=turn, observed=observed, transcript=(observed,)
        )
        self.assertIn("once upon a time\\nthere was Raju", payload)
        self.assertIn("each line is a separate chat bubble", system)


class _FlakyDriver:
    """Fails the first `failures` sample runs, then returns one observed turn."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def run_sample(self, scenario: BehaviorScenario, sample_index: int):
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError("provider stalled")
        return (_observed("fair enough"),)


class CrashedSampleTest(unittest.IsolatedAsyncioTestCase):
    def _scenario(self, scenario_id: str) -> BehaviorScenario:
        return BehaviorScenario(
            id=scenario_id,
            description="d",
            turns=(ScenarioTurn("hi", TurnExpectation(maximum_questions=None)),),
        )

    async def _run(self, driver: _FlakyDriver, *ids: str):
        return await run_behavior_evals(
            scenarios=tuple(self._scenario(item) for item in ids),
            driver=driver,
            judge=None,
            config=BehaviorEvalConfig(suite_name="t"),
        )

    async def test_a_crash_is_retried_once(self) -> None:
        driver = _FlakyDriver(failures=1)
        report = await self._run(driver, "one")
        self.assertEqual(driver.calls, 2)
        self.assertTrue(report.scenarios[0].samples[0].passed)

    async def test_a_repeated_crash_fails_that_sample_but_the_run_continues(self) -> None:
        driver = _FlakyDriver(failures=2)
        report = await self._run(driver, "broken", "fine")
        broken, fine = report.scenarios
        self.assertEqual(broken.samples[0].error, "TimeoutError: provider stalled")
        self.assertFalse(broken.passed)
        self.assertTrue(fine.passed)
        markdown = "\n".join(_scenario_markdown(report_payload(report)["scenarios"][0]))
        self.assertIn("**Error:** the conversation could not run: TimeoutError", markdown)


class CompanionV2CatalogueTest(unittest.TestCase):
    def test_scenarios_are_timed_tagged_and_unique(self) -> None:
        ids = [scenario.id for scenario in COMPANION_V2_SCENARIOS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 10)
        for scenario in COMPANION_V2_SCENARIOS:
            with self.subTest(scenario=scenario.id):
                self.assertIn("companion_v2", scenario.tags)
                self.assertIsNotNone(scenario.start_at)
                for turn in scenario.turns:
                    # Technical gate only: every reply keeps the question rules, no taste scores.
                    self.assertEqual(turn.expectation.maximum_questions, 1)
                    self.assertEqual(turn.expectation.maximum_question_streak, 2)
                    self.assertNotIn(
                        "naturalness", {dimension.id for dimension in turn.expectation.rubric}
                    )
        start = datetime.fromisoformat(COMPANION_V2_SCENARIOS[0].start_at)
        self.assertEqual(start.strftime("%A"), "Monday")

    def test_cli_selects_the_v2_set(self) -> None:
        # Importing the CLI loads .env into os.environ; restore it so other tests are unaffected.
        saved_environment = dict(os.environ)
        sys.path.insert(0, str(SCRIPTS))
        try:
            import run_behavior_evals
        finally:
            sys.path.remove(str(SCRIPTS))
            os.environ.clear()
            os.environ.update(saved_environment)
        selected = run_behavior_evals._selected_scenarios(None, scenario_set="companion_v2")
        self.assertEqual(selected, COMPANION_V2_SCENARIOS)
        one = run_behavior_evals._selected_scenarios(
            ["format_story_in_bubbles"], scenario_set="companion_v2"
        )
        self.assertEqual([scenario.id for scenario in one], ["format_story_in_bubbles"])


if __name__ == "__main__":
    unittest.main()
