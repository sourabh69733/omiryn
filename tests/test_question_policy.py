import os
import unittest
from unittest.mock import patch

from agent.context_engine.contracts.models import ConversationPlan
from agent.context_engine.conversation_engine.planning import apply_question_cooldown
from agent.context_engine.conversation_engine.planning.planner import recent_question_streak
from agent.context_engine.engine import build_model_context_package
from storage import reset_db, save_conversation


def _chat(*replies: str) -> list[dict]:
    messages = []
    for reply in replies:
        messages += [{"role": "user", "content": "hmm"}, {"role": "assistant", "content": reply}]
    return messages


class QuestionStreakTest(unittest.TestCase):
    def test_streak_counts_latest_replies_that_asked(self) -> None:
        self.assertEqual(recent_question_streak(_chat("ok", "which one?", "why?")), 2)
        self.assertEqual(recent_question_streak(_chat("which one?", "nice")), 0)
        self.assertEqual(recent_question_streak([]), 0)

    def test_bubbles_of_one_reply_count_once(self) -> None:
        messages = _chat("which one?") + [
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "haha"},
            {"role": "assistant", "content": "was it any good?"},
        ]
        self.assertEqual(recent_question_streak(messages), 2)

    def test_cooldown_silences_optional_questions_only(self) -> None:
        asked_twice = _chat("which one?", "why though?")
        for purpose in ("optional", "deepen", "offer_choice"):
            with self.subTest(purpose=purpose):
                plan = ConversationPlan(current_move="react", question_purpose=purpose)
                self.assertEqual(apply_question_cooldown(plan, asked_twice).question_purpose, "none")
        for purpose in ("clarify", "challenge"):
            with self.subTest(purpose=purpose):
                plan = ConversationPlan(current_move="react", question_purpose=purpose)
                self.assertEqual(apply_question_cooldown(plan, asked_twice).question_purpose, purpose)
        plan = ConversationPlan(current_move="react", question_purpose="deepen")
        self.assertEqual(apply_question_cooldown(plan, _chat("which one?")).question_purpose, "deepen")


class QuestionPolicyPromptTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def _prompt(self, messages: list[dict], user_text: str) -> str:
        save_conversation({"id": "c", "status": "active", "messages": messages}, "u")
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}):
            return build_model_context_package(
                conversation_id="c",
                user_text=user_text,
                user_id="u",
                user_profile={},
                model=None,
                agent_tone="auto",
                agent_name=None,
                style_source_id=None,
                user_message_index=len(messages),
                assistant_message_index=len(messages) + 1,
            ).system_prompt

    def test_two_questions_in_a_row_forbid_a_third(self) -> None:
        prompt = self._prompt(_chat("which one?", "was it any good?"), "I felt so lonely at the party")
        self.assertIn("Do not ask a question in this reply.", prompt)

    def test_default_guidance_makes_questions_optional(self) -> None:
        prompt = self._prompt([], "we might order pizza")
        self.assertIn("A question is optional", prompt)
        self.assertNotIn("ask at most one natural question", prompt)

    def test_story_request_is_not_steered_to_the_users_childhood(self) -> None:
        prompt = self._prompt([], "tell me a story about a chai stall owner in Mumbai")
        self.assertNotIn("Personal stories: childhood", prompt)


if __name__ == "__main__":
    unittest.main()
