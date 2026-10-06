"""Prompt v4: a character and a goal, context in tagged blocks, facts instead of the keyword plan."""

import os
import re
import unittest
from unittest.mock import patch

from agent.context_engine.engine import build_model_context_package
from agent.context_engine.prompt_engine.blocks import BLOCK_CHAR_LIMITS, turn_facts
from storage import add_open_questions, create_agent_memory, reset_db, save_conversation, set_user_card

USER_ID = "v4-user"
CONVERSATION_ID = "v4-chat"
ORDER = ["omi", "rules", "format", "about_user", "this_chat", "this_turn", "goal"]


def _chat(*pairs: tuple[str, str]) -> list[dict]:
    messages = []
    for user, assistant in pairs:
        messages += [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]
    return messages


class PromptV4Test(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def _package(self, messages: list[dict], user_text: str):
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": messages}, USER_ID)
        env = {
            "AGENT_PIPELINE_VERSION": "v3",
            "AGENT_BEHAVIOR_VERSION": "v4",
            "MEMORY_EMBEDDING_MODEL": "off",
        }
        with patch.dict(os.environ, env):
            return build_model_context_package(
                conversation_id=CONVERSATION_ID,
                user_text=user_text,
                user_id=USER_ID,
                user_profile={"display_name": "Sourabh"},
                model=None,
                agent_tone="auto",
                agent_name=None,
                style_source_id=None,
                user_message_index=len(messages),
                assistant_message_index=len(messages) + 1,
            )

    def test_blocks_come_in_order_stable_first_and_this_turn_last(self) -> None:
        set_user_card(USER_ID, "Loves old films; has a sister, Riya.")
        package = self._package(_chat(("hi", "hey! how was today?")), "pretty chill")
        prompt = package.system_prompt

        self.assertEqual(package.prompt_version, "v4")
        found = re.findall(r"^<([a-z_]+)>$", prompt, re.M)
        self.assertEqual([tag for tag in found if tag in ORDER], [tag for tag in ORDER if tag in found])
        self.assertEqual(found[0], "omi")
        self.assertEqual(found[-1], "goal")
        about_user = prompt.split("<about_user>")[1].split("</about_user>")[0]
        self.assertIn("Loves old films", about_user)

    def test_no_keyword_plan_in_the_prompt(self) -> None:
        prompt = self._package(_chat(("hi", "hey!")), "hmm").system_prompt

        for leftover in ("Conversation plan", "Move:", "Response mode", "low_information", "## "):
            self.assertNotIn(leftover, prompt)
        self.assertIn("Your character:", prompt)

    def test_this_turn_states_facts_and_a_question_streak_removes_the_question(self) -> None:
        package = self._package(
            _chat(("hi", "which film?"), ("old one", "was it good?")), "hain??"
        )
        this_turn = package.system_prompt.split("<this_turn>")[1].split("</this_turn>")[0]

        self.assertIn("Their latest message: 1 word, and it asks something.", this_turn)
        self.assertIn("Your last reply asked them a question.", this_turn)
        self.assertIn("do not ask one now", this_turn)
        self.assertEqual(package.question_limit, 0)

    def test_a_short_reply_alone_does_not_remove_the_question(self) -> None:
        package = self._package(_chat(("hi", "nice evening.")), "hmm")

        self.assertEqual(package.question_limit, 1)

    def test_a_no_questions_request_still_holds_a_turn_later(self) -> None:
        package = self._package(
            _chat(("Bas suno, sawal mat puchna.", "Okay, I'm listening.")),
            "I'm still upset about work.",
        )
        this_turn = package.system_prompt.split("<this_turn>")[1].split("</this_turn>")[0]

        self.assertIn("A few messages ago: they asked you not to ask questions.", this_turn)
        self.assertEqual(package.question_limit, 0)

    def test_how_to_talk_memories_sit_in_their_own_block_before_this_turn(self) -> None:
        save_conversation(
            {"id": "source", "status": "completed", "messages": [{"role": "user", "content": "No questions please."}]},
            USER_ID,
        )
        create_agent_memory(
            {
                "user_id": USER_ID,
                "kind": "procedural",
                "purposes": ["personalization"],
                "key": "reply_style",
                "value": "no questions",
                "statement": "The user wants no questions from the companion.",
                "confidence": 0.9,
                "importance": 0.9,
                "evidence": [
                    {"conversation_id": "source", "message_index": 0, "exact_quote": "No questions please.", "observed_at": "2026-10-01T10:00:00+00:00"}
                ],
            }
        )
        prompt = self._package([], "tell me about space").system_prompt

        block = prompt.split("<how_to_talk>")[1].split("</how_to_talk>")[0]
        self.assertIn("wants no questions", block)
        self.assertLess(prompt.index("<how_to_talk>"), prompt.index("<this_turn>"))
        self.assertNotIn("wants no questions", prompt.split("<memories>")[1].split("</memories>")[0] if "<memories>" in prompt else "")

    def test_an_open_question_sits_in_its_own_block(self) -> None:
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": []}, USER_ID)
        add_open_questions(USER_ID, CONVERSATION_ID, [{"id": "q", "text": "Moved, or only visiting?", "message_index": 0}])

        prompt = self._package([], "hey").system_prompt

        self.assertIn("You are unsure: Moved, or only visiting?", prompt.split("<open_questions>")[1].split("</open_questions>")[0])
        self.assertLess(prompt.index("<open_questions>"), prompt.index("<this_turn>"))

    def test_memory_lines_keep_their_line_breaks(self) -> None:
        set_user_card(USER_ID, "Line one.\nLine two.")
        prompt = self._package([], "hey").system_prompt

        self.assertIn("Line one.\nLine two.", prompt)

    def test_v4_is_the_default(self) -> None:
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": []}, USER_ID)
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}):
            os.environ.pop("AGENT_BEHAVIOR_VERSION", None)
            package = build_model_context_package(
                conversation_id=CONVERSATION_ID,
                user_text="hey",
                user_id=USER_ID,
                user_profile={},
                model=None,
                agent_tone="auto",
                agent_name=None,
                style_source_id=None,
                user_message_index=0,
                assistant_message_index=1,
            )
        self.assertEqual(package.prompt_version, "v4")


class TurnFactsTest(unittest.TestCase):
    def test_facts_come_from_the_messages(self) -> None:
        facts = turn_facts(
            [{"role": "assistant", "content": "Tea or coffee?"}, {"role": "user", "content": "both, why?"}],
            question_streak=1,
        )

        self.assertEqual((facts.user_words, facts.user_asked, facts.omi_last_asked), (2, True, True))

    def test_every_block_has_a_limit(self) -> None:
        self.assertTrue(set(ORDER) <= set(BLOCK_CHAR_LIMITS))


if __name__ == "__main__":
    unittest.main()
