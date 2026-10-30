"""Omi's questions in this chat, with what the user said next, reach the reply and the request check.

Seen live (progress 6c): "kya kar rahe ho abhi?" asked five times in twenty minutes, after the user
answered around it and after "do not ask stupid questions". Code now computes the facts; the model
judges what a brush-off means.
"""

import json
import os
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from agent.context_engine.policy.asked_questions import asked_question_lines, asked_questions
from agent.context_engine.policy.requests import asked_question_requests, broken_requests, request_check_input
from agent.context_engine.sources.asked_questions import asked_question_sources
from agent.runtime.orchestrator import run_agent_turn
from agent.runtime.steps import ReplyJob, follow_requests
from agent.shared.clock import utc_now
from storage import reset_db, save_conversation

USER_ID = "asked-user"
NOW = utc_now()


def _chat(*turns: tuple[str, str], minutes_apart: float = 2) -> list[dict]:
    start = NOW - timedelta(minutes=minutes_apart * len(turns))
    return [
        {"role": role, "content": text, "created_at": (start + timedelta(minutes=minutes_apart * index)).isoformat()}
        for index, (role, text) in enumerate(turns)
    ]


THE_6C_CHAT = _chat(
    ("user", "hi"),
    ("assistant", "Hey! Kya kar rahe ho abhi?"),
    ("user", "bas yaar, din lamba tha"),
    ("assistant", "Samajh sakta hoon. Toh abhi kya kar rahe ho?"),
    ("user", "do not ask stupid questions"),
    ("assistant", "Theek hai, I'll stop asking questions."),
    ("user", "english?"),
)


class AskedQuestionFactsTest(unittest.TestCase):
    def test_the_same_question_in_new_words_is_one_question_with_each_answer(self) -> None:
        [asked] = asked_questions(THE_6C_CHAT, now=NOW)
        self.assertEqual(asked.question, "Kya kar rahe ho abhi?")
        self.assertEqual(asked.times, 2)
        self.assertEqual(asked.user_said, ["bas yaar, din lamba tha", "do not ask stupid questions"])
        self.assertTrue(all(label.endswith("ago") for label in asked.asked_ago))

    def test_a_question_with_no_reply_yet_says_so_and_short_ones_are_skipped(self) -> None:
        chat = _chat(("user", "hi"), ("assistant", "Hey! Weekend pe kya plan hai? Aur?"))
        [asked] = asked_questions(chat, now=NOW)
        self.assertEqual((asked.question, asked.user_said), ("Weekend pe kya plan hai?", [None]))
        self.assertIn("nothing yet", asked_question_lines([asked])[0])

    def test_only_the_current_session_counts_and_deleted_messages_are_skipped(self) -> None:
        old = _chat(("assistant", "Kal exam kaisa gaya tha?"), ("user", "theek tha"))
        for message in old:
            message["created_at"] = (NOW - timedelta(days=2)).isoformat()
        recent = _chat(("assistant", "Aaj kya khaya tumne?"), ("user", "deleted", ), ("assistant", "ok"))
        recent[1]["deleted"] = True
        asked = asked_questions([*old, *recent], now=NOW)
        self.assertEqual([item.question for item in asked], ["Aaj kya khaya tumne?"])
        self.assertEqual(asked[0].user_said, [None])

    def test_the_source_block_lists_the_questions_with_the_rule(self) -> None:
        reset_db()
        save_conversation({"id": "c", "status": "active", "messages": THE_6C_CHAT}, USER_ID)
        [source] = asked_question_sources("c", USER_ID)
        self.assertEqual(source["source_type"], "asked_questions")
        self.assertIn('"Kya kar rahe ho abhi?" (asked 2 times:', source["content"])
        self.assertIn('"do not ask stupid questions"', source["content"])
        self.assertIn("Do not ask a listed question again in any words", source["content"])
        self.assertEqual(asked_question_sources("c", None), [])


class CheckerInputTest(unittest.IsolatedAsyncioTestCase):
    def test_the_checker_reads_the_questions_and_may_name_one_as_broken(self) -> None:
        asked = asked_questions(THE_6C_CHAT, now=NOW)
        payload = json.loads(request_check_input("Aur abhi kya chal raha hai?", [], ["english?"], asked))
        self.assertEqual(payload["asked_questions"], [
            {"question": "Kya kar rahe ho abhi?", "times": 2, "user_said": ["bas yaar, din lamba tha", "do not ask stupid questions"]}
        ])
        given = asked_question_requests(asked)
        self.assertEqual(given, ['do not ask again: "Kya kar rahe ho abhi?"'])
        self.assertEqual(broken_requests({"broken": given + ["made up"]}, given), given)

    async def test_a_re_asked_closed_question_gets_a_rewrite(self) -> None:
        asked = asked_questions(THE_6C_CHAT, now=NOW)
        checker = AsyncMock(return_value={"broken": ['do not ask again: "Kya kar rahe ho abhi?"']})
        writer = AsyncMock(return_value="Okay, English it is. Long day, sounds like.")
        job = ReplyJob(THE_6C_CHAT, {"conversation_id": "c"}, writer, history=THE_6C_CHAT[:-1], user_text="english?", asked=asked)
        with patch("agent.runtime.steps.checks.check_reply_requests", checker):
            reply, info = await follow_requests("Sure! So, what are you up to right now?", job)
        self.assertEqual(reply, "Okay, English it is. Long day, sounds like.")
        self.assertEqual(info["broken"], ['do not ask again: "Kya kar rahe ho abhi?"'])
        self.assertIn("Kya kar rahe ho abhi?", json.loads(checker.await_args.args[0])["asked_questions"][0]["question"])


class LiveTurnTest(unittest.IsolatedAsyncioTestCase):
    """The whole turn: the reply model's prompt and the checker both see the asked questions."""

    async def test_the_prompt_and_the_checker_see_the_questions(self) -> None:
        reset_db()
        # The mock reply asks nothing, so the gate would skip the checker; "always" shows its input.
        env = {"AGENT_PROVIDER": "mock", "AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off",
               "AGENT_FRESHNESS_CHECK": "false", "DATA_POINT_EXTRACTOR": "rules", "AGENT_REQUEST_CHECK": "always"}
        save_conversation({"id": "c", "status": "active", "messages": THE_6C_CHAT}, USER_ID)
        checker = AsyncMock(return_value={"broken": []})
        with patch.dict(os.environ, env), patch("agent.runtime.steps.checks.check_reply_requests", checker):
            result = await run_agent_turn(
                conversation_id="c", messages=THE_6C_CHAT[:-1], user_text="english?", user_id=USER_ID,
                user_profile=None, model=None, agent_mode="know_me", agent_tone="auto", style_source_id=None,
            )
        self.assertTrue(result.messages[-1]["content"])
        payload = json.loads(checker.await_args.args[0])
        self.assertEqual(payload["asked_questions"][0]["times"], 2)
        self.assertEqual(payload["asked_questions"][0]["user_said"][-1], "do not ask stupid questions")


if __name__ == "__main__":
    unittest.main()
