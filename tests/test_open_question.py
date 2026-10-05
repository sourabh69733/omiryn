"""A short confused reply or an answer to Omi never gets an old subject instead of an answer."""

import unittest

from agent.context_engine.contracts.models import ThreadGuidance, ThreadReference
from agent.context_engine.conversation_engine.planning import (
    build_conversation_plan,
    hold_old_topics_while_a_question_is_open,
)
from agent.context_engine.conversation_engine.understanding.rules.intent import context_query_intent
from agent.context_engine.prompt_engine.modules.conversation_flow import conversation_plan_prompt

OLD_TOPIC = ThreadGuidance(
    relevant_open=(
        ThreadReference(
            id="t1",
            title="Upcoming tech interview",
            origin="user_started",
            user_interest="high",
            cross_session=True,
        ),
    )
)


def _plan(user_text: str, messages: list[dict]):
    plan = build_conversation_plan(
        user_text=user_text,
        intent=context_query_intent(user_text),
        thread_guidance=OLD_TOPIC,
    )
    return hold_old_topics_while_a_question_is_open(
        plan, messages + [{"role": "user", "content": user_text}]
    )


class OpenQuestionTest(unittest.TestCase):
    def test_a_confused_short_reply_gets_an_answer_not_an_old_topic(self) -> None:
        plan = _plan("hain??", [{"role": "assistant", "content": "Silent nights can be nice, though!"}])

        self.assertEqual(plan.thread_action, "follow_user")
        self.assertIsNone(plan.thread_title)

    def test_a_short_answer_to_omis_question_stays_on_it(self) -> None:
        plan = _plan("yeah", [{"role": "assistant", "content": "Do you play anything yourself?"}])

        self.assertEqual(plan.thread_action, "follow_user")

    def test_a_quiet_ok_can_still_bring_back_the_users_own_topic(self) -> None:
        plan = _plan("ok", [{"role": "assistant", "content": "That sounds like a fun weekend."}])

        self.assertEqual(plan.thread_action, "offer_open")
        self.assertEqual(plan.thread_title, "Upcoming tech interview")

    def test_the_reply_goal_says_answer_first(self) -> None:
        prompt = conversation_plan_prompt(_plan("hain??", []))

        self.assertIn("answer that first", prompt)
        self.assertNotIn("Upcoming tech interview", prompt)


if __name__ == "__main__":
    unittest.main()
