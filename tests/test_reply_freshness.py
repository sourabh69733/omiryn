import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.conversation_engine.policy.freshness import (
    question_rule_reason,
    recent_assistant_replies,
    rewrite_instruction,
    stale_reply_reason,
    trim_questions,
)
from agent.runtime.orchestrator import _freshen_reply, _turn_notes


class StaleReplyTest(unittest.TestCase):
    def test_stock_lines_are_caught_regardless_of_case_and_punctuation(self) -> None:
        self.assertIn("what's on your mind", stale_reply_reason("Hey! What’s on your mind today?", []))
        self.assertIn("that sounds like fun", stale_reply_reason("That sounds like FUN!!", []))

    def test_specific_reply_passes(self) -> None:
        self.assertIsNone(
            stale_reply_reason("a presentation win on a Monday? your manager has taste", ["long day at work?"])
        )

    def test_near_copy_of_an_earlier_reply_is_caught(self) -> None:
        earlier = ["long day at work? hope you get some rest tonight"]
        reason = stale_reply_reason("Long day at work? Hope you get some rest tonight!", earlier)
        self.assertIn("nearly repeats", reason)

    def test_short_replies_may_repeat(self) -> None:
        self.assertIsNone(stale_reply_reason("haha same", ["haha same", "haha same"]))

    def test_repeated_opening_is_caught_on_the_third_use(self) -> None:
        earlier = ["that's awesome, congrats on the promotion", "that's awesome, the trek sounds wild"]
        reason = stale_reply_reason("that's awesome, your sister must be thrilled", earlier)
        self.assertIn('opens with "that\'s awesome"', reason)
        self.assertIsNone(stale_reply_reason("that's awesome, your sister must be thrilled", earlier[:1]))

    def test_bubble_separator_does_not_hide_a_stock_line(self) -> None:
        self.assertIsNotNone(stale_reply_reason("hmm<next_message>I'm here for you", []))

    def test_question_limits(self) -> None:
        self.assertIsNone(question_rule_reason("which one?", 1))
        self.assertIn("2 questions", question_rule_reason("best part?<next_message>new trail?", 1))
        self.assertIn("must not ask any", question_rule_reason("which one?", 0))
        self.assertIsNone(question_rule_reason("fair enough", 0))

    def test_trim_questions_drops_extra_questions_but_never_empties(self) -> None:
        separator = "<next_message>"
        self.assertEqual(trim_questions(f"which one?{separator}was it any good?", 1), "which one?")
        self.assertEqual(
            trim_questions(f"boring movies can be a drag.{separator}what did you expect?", 0),
            "boring movies can be a drag.",
        )
        self.assertEqual(trim_questions(f"which one?{separator}was it good?", 0), "which one?")
        self.assertEqual(trim_questions("Raju made chai. Want more?", 1), "Raju made chai. Want more?")

    def test_turn_notes(self) -> None:
        self.assertEqual(_turn_notes(1), [])
        self.assertIn("Do not ask any question", _turn_notes(0)[0]["content"])
        story = _turn_notes(0, ("story_or_long_reply",))
        self.assertEqual(len(story), 1)
        self.assertIn("tell it yourself now in 4-7 short bubbles", story[0]["content"])

    def test_recent_replies_and_rewrite_instruction(self) -> None:
        messages = [
            {"role": "assistant", "content": "hey"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "how was the day?"},
        ]
        self.assertEqual(recent_assistant_replies(messages), ["hey", "how was the day?"])
        instruction = rewrite_instruction("That sounds like fun!", "it uses a stock line")
        self.assertIn('"That sounds like fun!"', instruction)
        self.assertIn("responds specifically to the user's latest message", instruction)


class FreshenReplyTest(unittest.IsolatedAsyncioTestCase):
    async def _freshen(self, reply: str, generate: AsyncMock) -> tuple[str, dict | None]:
        with patch("agent.runtime.orchestrator.generate_agent_reply", new=generate):
            return await _freshen_reply(
                reply,
                previous_replies=[],
                reply_messages=[{"role": "user", "content": "my manager praised my presentation"}],
                generation_arguments={"system_prompt": "SYSTEM"},
            )

    async def test_stale_draft_is_rewritten_once(self) -> None:
        generate = AsyncMock(return_value="your manager noticed, that's a big deal. what did they say?")
        reply, freshness = await self._freshen("That sounds amazing!", generate)

        self.assertEqual(reply, "your manager noticed, that's a big deal. what did they say?")
        self.assertTrue(freshness["rewritten"])
        self.assertFalse(freshness["still_stale"])
        generate.assert_awaited_once()
        self.assertIn("Rewrite needed", generate.await_args.kwargs["system_prompt"])

    async def test_fresh_draft_makes_no_extra_call(self) -> None:
        generate = AsyncMock()
        reply, freshness = await self._freshen("your manager has good taste", generate)
        self.assertEqual((reply, freshness), ("your manager has good taste", None))
        generate.assert_not_awaited()

    async def test_failed_rewrite_keeps_the_draft(self) -> None:
        reply, freshness = await self._freshen(
            "That sounds amazing!", AsyncMock(side_effect=RuntimeError("provider down"))
        )
        self.assertEqual(reply, "That sounds amazing!")
        self.assertEqual(freshness["error"], "RuntimeError")

    async def test_question_limit_breaks_trigger_a_rewrite(self) -> None:
        generate = AsyncMock(return_value="a week of launches, you've earned a quiet night")
        with patch("agent.runtime.orchestrator.generate_agent_reply", new=generate):
            reply, freshness = await _freshen_reply(
                "hope it calms down, how's Bruno handling it?",
                previous_replies=[],
                reply_messages=[{"role": "user", "content": "work was hectic"}],
                generation_arguments={"system_prompt": "SYSTEM"},
                question_limit=0,
            )
        self.assertEqual(reply, "a week of launches, you've earned a quiet night")
        self.assertIn("must not ask any", freshness["reason"])
        self.assertFalse(freshness["still_stale"])

    async def test_rewrite_that_still_asks_is_trimmed(self) -> None:
        generate = AsyncMock(return_value="which one?<next_message>was it any good?")
        with patch("agent.runtime.orchestrator.generate_agent_reply", new=generate):
            reply, freshness = await _freshen_reply(
                "which one?<next_message>was it any good?",
                previous_replies=[],
                reply_messages=[{"role": "user", "content": "watched a movie"}],
                generation_arguments={"system_prompt": "SYSTEM"},
                question_limit=1,
            )
        self.assertEqual(reply, "which one?")
        self.assertTrue(freshness["questions_trimmed"])
        self.assertFalse(freshness["still_stale"])

    async def test_check_can_be_switched_off(self) -> None:
        generate = AsyncMock()
        with patch.dict(os.environ, {"AGENT_FRESHNESS_CHECK": "false"}):
            reply, freshness = await self._freshen("That sounds amazing!", generate)
        self.assertEqual((reply, freshness), ("That sounds amazing!", None))
        generate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
