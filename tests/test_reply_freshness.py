import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.policy.freshness import (
    question_rule_reason,
    recent_assistant_replies,
    rewrite_instruction,
    stale_reply_reason,
    trim_questions,
)
from agent.runtime.steps import ReplyJob, freshen_reply, turn_notes as _turn_notes


async def _freshen_reply(reply, *, previous_replies, reply_messages, generation_arguments, generate, question_limit=1):
    job = ReplyJob(reply_messages, generation_arguments, generate, question_limit=question_limit, previous_replies=previous_replies)
    return await freshen_reply(reply, job)


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

    def test_repeated_opening_is_caught_right_after_or_on_the_third_use(self) -> None:
        draft = "that's awesome, your sister must be thrilled"
        promotion = "that's awesome, congrats on the promotion"
        trek = "that's awesome, the trek sounds wild"
        other = "wow, what a week you had"
        self.assertIn('opens with "that\'s awesome"', stale_reply_reason(draft, [promotion]))
        self.assertIn('opens with "that\'s awesome"', stale_reply_reason(draft, [promotion, trek, other]))
        self.assertIsNone(stale_reply_reason(draft, [promotion, other]))

    def test_bubble_separator_does_not_hide_a_stock_line(self) -> None:
        self.assertIsNotNone(stale_reply_reason("hmm<next_message>I'm here for you", []))

    def test_question_limits(self) -> None:
        self.assertIsNone(question_rule_reason("which one?", 1))
        self.assertIn("2 questions", question_rule_reason("best part?<next_message>new trail?", 1))
        self.assertIn("must not ask any", question_rule_reason("which one?", 0))
        self.assertIsNone(question_rule_reason("fair enough", 0))

    def test_trim_questions_drops_extra_questions_but_never_empties(self) -> None:
        separator = "<next_message>"
        self.assertEqual(trim_questions(f"which one?{separator}was it any good?", 1), "was it any good?")
        self.assertEqual(
            trim_questions(f"boring movies can be a drag.{separator}what did you expect?", 0),
            "boring movies can be a drag.",
        )
        self.assertEqual(trim_questions(f"which one?{separator}was it good?", 0), "was it good?")
        self.assertEqual(trim_questions("Raju made chai. Want more?", 1), "Raju made chai. Want more?")
        # A bare echo goes first, and a lead-in does not hang once its question is dropped.
        self.assertEqual(
            trim_questions("Kuch bhi? Chalo, maine socha... ek purani film dekhein aaj?", 1),
            "Chalo, maine socha... ek purani film dekhein aaj?",
        )
        self.assertEqual(trim_questions("Nice. Maine socha... film dekhein?", 0), "Nice.")

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
        return await _freshen_reply(
            reply,
            previous_replies=[],
            reply_messages=[{"role": "user", "content": "my manager praised my presentation"}],
            generation_arguments={"system_prompt": "SYSTEM"},
            generate=generate,
        )

    async def test_stale_draft_is_rewritten_once(self) -> None:
        generate = AsyncMock(return_value="your manager noticed, that's a big deal. what did they say?")
        reply, freshness = await self._freshen("That sounds amazing!", generate)

        self.assertEqual(reply, "your manager noticed, that's a big deal. what did they say?")
        self.assertTrue(freshness["rewritten"])
        self.assertFalse(freshness["still_stale"])
        generate.assert_awaited_once()
        self.assertEqual(generate.await_args.kwargs["system_prompt"], "SYSTEM")
        self.assertIn("Rewrite needed", generate.await_args.args[0][-1]["content"])

    async def test_rewrite_does_not_see_the_reply_it_copied(self) -> None:
        greeting = "Shaam ho rahi hai, Sourabh! Toh padhai complete kar liya?"
        generate = AsyncMock(return_value="hi again!")
        history = [
            {"role": "assistant", "content": greeting},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "what are you up to"},
            {"role": "user", "content": "hi"},
        ]
        reply, freshness = await _freshen_reply(
            greeting,
            previous_replies=[greeting, "what are you up to"],
            reply_messages=history,
            generation_arguments={"system_prompt": "SYSTEM"},
            generate=generate,
        )
        self.assertEqual(reply, "hi again!")
        sent = generate.await_args.args[0]
        self.assertNotIn(greeting, [message["content"] for message in sent])
        self.assertIn("what are you up to", [message["content"] for message in sent])
        self.assertEqual(sent[-1]["role"], "system")
        self.assertNotIn("Shaam", sent[-1]["content"])

    async def test_a_copy_with_a_new_bubble_is_still_a_copy(self) -> None:
        greeting = "Shaam ho rahi hai, Sourabh! Toh padhai complete kar liya?"
        self.assertIsNotNone(
            stale_reply_reason(f"{greeting}<next_message>Aaj ka plan kya hai bhai?", [greeting])
        )

    async def test_the_same_question_reworded_is_a_copy(self) -> None:
        self.assertIsNotNone(
            stale_reply_reason("Sham ho gayi, abhi kya kar rahe ho?", ["Sham ho gayi! Kya kar rahe ho abhi?"])
        )
        self.assertIsNone(stale_reply_reason("Kya plan hai weekend ka?", ["Sham ho gayi! Kya kar rahe ho abhi?"]))

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
        reply, freshness = await _freshen_reply(
            "hope it calms down, how's Bruno handling it?",
            previous_replies=[],
            reply_messages=[{"role": "user", "content": "work was hectic"}],
            generation_arguments={"system_prompt": "SYSTEM"},
            generate=generate,
            question_limit=0,
        )
        self.assertEqual(reply, "a week of launches, you've earned a quiet night")
        self.assertIn("must not ask any", freshness["reason"])
        self.assertFalse(freshness["still_stale"])

    async def test_rewrite_that_still_asks_is_trimmed(self) -> None:
        generate = AsyncMock(return_value="which one?<next_message>was it any good?")
        reply, freshness = await _freshen_reply(
            "which one?<next_message>was it any good?",
            previous_replies=[],
            reply_messages=[{"role": "user", "content": "watched a movie"}],
            generation_arguments={"system_prompt": "SYSTEM"},
            generate=generate,
            question_limit=1,
        )
        self.assertEqual(reply, "was it any good?")
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


class RepeatedQuestionTest(unittest.TestCase):
    """Seen live: "kya kar rahe ho abhi?" five times in 20 minutes, each inside a new reply."""

    PREVIOUS = ["Arre wah! Toh kya kar rahe ho abhi?", "Sahi hai."]

    def test_a_question_asked_before_is_caught_inside_a_new_reply(self) -> None:
        from agent.context_engine.policy.freshness import stale_reply_reason

        reason = stale_reply_reason("Theek hai, no worries. Waise abhi kya kar rahe ho?", self.PREVIOUS)
        self.assertIn("a question you already asked", reason)

    def test_new_and_short_questions_are_fine(self) -> None:
        from agent.context_engine.policy.freshness import repeated_questions

        self.assertEqual(repeated_questions("Kal ka match dekha tumne?", self.PREVIOUS), [])
        self.assertEqual(repeated_questions("Haha, and you?", ["Same here, and you?"]), [])

    def test_last_resort_drops_the_repeated_question_but_never_empties_the_reply(self) -> None:
        from agent.context_engine.policy.freshness import without_repeated_questions

        reply = "Theek hai, no worries.<next_message>Waise kya kar rahe ho abhi?"
        self.assertEqual(without_repeated_questions(reply, self.PREVIOUS), "Theek hai, no worries.")
        self.assertEqual(without_repeated_questions("Kya kar rahe ho abhi?", self.PREVIOUS), "Kya kar rahe ho abhi?")

    def test_a_different_question_with_shared_words_is_fine(self) -> None:
        from agent.context_engine.policy.freshness import repeated_questions

        self.assertEqual(repeated_questions("What are you doing this weekend?", ["What are you doing now?"]), [])


class SameShapeRepeatTest(unittest.TestCase):
    """Seen live on Gemma: the same reply twice with only the middle words changed."""

    FIRST = "theek hai, main silent mode pe ja raha hoon. jab mann kare tab bata dena."
    SECOND = "theek hai, main chup hoon. jab mood ho tab bata dena."

    def test_the_same_start_and_end_with_a_new_middle_is_a_repeat(self) -> None:
        from agent.context_engine.policy.freshness import stale_reply_reason

        self.assertIsNotNone(stale_reply_reason(self.SECOND, [self.FIRST]))

    def test_a_different_reply_that_shares_only_one_end_is_fine(self) -> None:
        from agent.context_engine.policy.freshness import _same_shape, _normalize

        self.assertFalse(_same_shape(_normalize("main ghar pe hoon abhi, kal bata dena."), _normalize(self.FIRST)))
        self.assertFalse(_same_shape(_normalize("theek hai, kal milte hain phir pakka."), _normalize(self.FIRST)))
        self.assertFalse(_same_shape(_normalize("theek hai bata dena"), _normalize(self.FIRST)))

    def test_opening_like_the_reply_right_before_it_is_stale(self) -> None:
        from agent.context_engine.policy.freshness import stale_reply_reason

        reason = stale_reply_reason("theek hai, kal ka plan pakka karte hain phir.", ["theek hai, main yahin hoon."])
        self.assertIn('opens with "theek hai"', reason)
        self.assertIsNone(stale_reply_reason("kal ka plan pakka karte hain phir.", ["theek hai, main yahin hoon."]))

    def test_last_resort_drops_a_repeated_opening_but_never_empties(self) -> None:
        from agent.context_engine.policy.freshness import without_repeated_opening

        earlier = ["theek hai, main yahin hoon."]
        self.assertEqual(without_repeated_opening("theek hai, kal baat karte hain.", earlier), "kal baat karte hain.")
        self.assertEqual(without_repeated_opening("theek hai.", earlier), "theek hai.")
        self.assertEqual(
            without_repeated_opening("theek hai.<next_message>kal baat karte hain.", earlier), "kal baat karte hain."
        )
        self.assertEqual(without_repeated_opening("kal baat karte hain.", earlier), "kal baat karte hain.")


class SeesWhatTheUserSeesTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_request_rewrite_that_repeats_is_caught_by_the_repeat_check(self) -> None:
        from agent.runtime.steps import REPLY_CHECKS

        self.assertEqual([name for name, _check in REPLY_CHECKS], ["request_check", "freshness"])
        first = SameShapeRepeatTest.FIRST
        job = ReplyJob(
            [{"role": "user", "content": "hmm"}],
            {"conversation_id": "c"},
            AsyncMock(side_effect=[SameShapeRepeatTest.SECOND, "hmm"]),
            requests=["Keep replies short."],
            previous_replies=[first],
        )
        reply = "kal ka kya plan hai tumhara phir?"
        with patch("agent.runtime.steps.checks.check_reply_requests", AsyncMock(return_value={"broken": ["Keep replies short."]})):
            for _name, check in REPLY_CHECKS:
                reply, _info = await check(reply, job)

        self.assertEqual(reply, "hmm")
        note = job.generate.await_args_list[1].args[0][-1]["content"]
        self.assertIn("say far less", note)

