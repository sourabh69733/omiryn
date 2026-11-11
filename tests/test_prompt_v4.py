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

    def test_v4_5_is_the_default_and_keeps_its_whole_character_and_goal(self) -> None:
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
        self.assertEqual(package.prompt_version, "v4-5")
        self.assertIn("Nothing happens to you between messages", package.system_prompt)
        # The character's last line survives its block's limit too.
        self.assertIn("one, then bring an opinion or turn to them.", package.system_prompt)
        self.assertIn("<no_reply> as your whole reply", package.system_prompt)
        # The goal's last line survives the block's limit.
        self.assertIn("conversation could produce.\n</goal>", package.system_prompt)


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


class AddressRuleTest(unittest.TestCase):
    def test_gender_is_only_assumed_when_the_user_chose_one(self) -> None:
        from agent.context_engine.prompt_engine.blocks import _address_rule

        self.assertIn("masculine", _address_rule({"gender": "man"}))
        self.assertIn("feminine", _address_rule({"gender": "woman"}))
        for gender in (None, "non_binary", "prefer_not_to_say"):
            with self.subTest(gender=gender):
                self.assertIn("not known", _address_rule({"gender": gender}))


class PromptV41Test(unittest.TestCase):
    def test_only_the_line_about_little_changes_and_v4_is_kept(self) -> None:
        from agent.context_engine.prompt_engine.versions.v4 import V4_GOAL
        from agent.context_engine.prompt_engine.versions.v4_1 import V4_1_GOAL, V4_1_PROMPT_VERSION

        self.assertIn("That is your cue to bring something", V4_GOAL)
        self.assertNotIn("That is your cue to bring something", V4_1_GOAL)
        self.assertIn("one word or one emoji", V4_1_GOAL)
        self.assertEqual(V4_1_PROMPT_VERSION.reply_goal, V4_1_GOAL)


class PromptV43Test(unittest.TestCase):
    def test_only_the_day_lines_change_and_v4_2_is_kept(self) -> None:
        from agent.context_engine.prompt_engine.versions.v4 import V4_CHARACTER
        from agent.context_engine.prompt_engine.versions.v4_2 import V4_2_GOAL, V4_2_PROMPT_VERSION
        from agent.context_engine.prompt_engine.versions.v4_3 import V4_3_CHARACTER, V4_3_GOAL

        self.assertIn("something you were curious about", V4_CHARACTER)
        self.assertNotIn("something you were curious about", V4_3_CHARACTER)
        self.assertIn("Nothing happens to you between messages", V4_3_CHARACTER)
        self.assertIn("not as something you saw or did", V4_3_GOAL)
        self.assertNotIn("not as something you saw or did", V4_2_GOAL)
        self.assertEqual(V4_2_PROMPT_VERSION.base_prompt, V4_CHARACTER)

    def test_omi_has_no_favourite_food_to_copy(self) -> None:
        from agent.context_engine.prompt_engine.versions.v4 import V4_CHARACTER
        from agent.context_engine.prompt_engine.versions.v4_3 import V4_3_CHARACTER

        self.assertIn("biryani", V4_CHARACTER)
        self.assertNotIn("biryani", V4_3_CHARACTER)
        self.assertNotIn("Dune", V4_3_CHARACTER)
        self.assertNotIn("music, food, ideas", V4_3_CHARACTER)
        self.assertIn("no favourite\n  food or drink", V4_3_CHARACTER)

    def test_versions_keep_the_settings_the_engine_lists_gave_them(self) -> None:
        from agent.context_engine.prompt_engine.registry import available_prompt_versions

        expected = {
            "v3": (False, True, False, True, "context_v3"),
            "v3-1": (False, True, True, True, "context_v3_1"),
            "v4": (True, True, True, True, "context_v4"),
            "v4-1": (True, True, True, True, "context_v4"),
            "v4-2": (True, True, True, True, "context_v4"),
            "v4-3": (True, True, True, True, "context_v4"),
            "v4-4": (True, True, True, True, "context_v4"),
            "v4-5": (True, True, True, True, "context_v4"),
        }
        actual = {
            v.version_id: (v.blocks_prompt, v.listener_first, v.matching_understanding, v.plans_turn, v.engine_version)
            for v in available_prompt_versions()
        }
        self.assertEqual(actual, expected)

    def test_omi_block_is_not_cut_with_any_voice_or_tone(self) -> None:
        from agent.context_engine.prompt_engine.blocks import _fit
        from agent.context_engine.prompt_engine.modules.identity import voice_prompt
        from agent.context_engine.prompt_engine.modules.tone import tone_module_prompt
        from agent.context_engine.prompt_engine.registry import available_prompt_versions

        limit = BLOCK_CHAR_LIMITS["omi"]
        for version in available_prompt_versions():
            if not version.blocks_prompt:
                continue
            for voice in ("neutral", "girl", "boy"):
                for tone in ("casual", "warm", "formal", "direct", "playful"):
                    parts = (version.base_prompt, voice_prompt(voice), tone_module_prompt(tone))
                    body = "\n\n".join(part.strip() for part in parts)
                    self.assertLessEqual(len(body), limit, (version.version_id, voice, tone))
                    self.assertEqual(_fit(body, limit), body)

    def test_v4_3_edits_still_find_the_text_they_replace(self) -> None:
        from agent.context_engine.prompt_engine.versions import v4_3
        from agent.context_engine.prompt_engine.versions.v4 import V4_CHARACTER
        from agent.context_engine.prompt_engine.versions.v4_2 import V4_2_GOAL

        # str.replace does nothing, with no error, when the old text has changed.
        for line in (v4_3._V4_DAY_LINE, v4_3._V4_TASTES_LINE, v4_3._V4_EXAMPLES_LINE):
            self.assertIn(line, V4_CHARACTER)
        for line in (v4_3._V4_2_BRING_LINE, v4_3._TEXT_LINE):
            self.assertIn(line, V4_2_GOAL)


class PromptV44Test(unittest.TestCase):
    """Omi can say who it is, what it can do and how chats are kept; funny like a friend."""

    def _prompt(self, version: str, sources: list | None = None) -> str:
        from agent.context_engine.prompt_engine.blocks import TurnFacts, build_companion_system_prompt_v4
        from agent.context_engine.prompt_engine.registry import get_prompt_behavior_version

        return build_companion_system_prompt_v4(
            context_sources=sources or [],
            user_profile={"display_name": "Riya"},
            agent_tone="auto",
            agent_name="Omi",
            prompt_version=get_prompt_behavior_version(version),
            matching_understanding=None,
            facts=TurnFacts(user_words=4, user_asked=True),
        )

    def test_v4_4_is_a_personal_friend_and_v4_3_is_unchanged(self) -> None:
        from agent.context_engine.prompt_engine.versions.v4_3 import V4_3_CHARACTER
        from agent.context_engine.prompt_engine.versions.v4_4 import V4_4_CHARACTER, V4_4_GOAL

        self.assertIn("an AI friend in the Omiryn app", V4_4_CHARACTER)
        self.assertNotIn("Omiryn helps people find friends", V4_4_CHARACTER)
        self.assertIn("never\n  a stock joke", V4_4_CHARACTER)
        self.assertIn("Oh no, that\n  sounds frustrating!", V4_4_GOAL)
        self.assertIn("Omiryn helps people find friends", V4_3_CHARACTER)

    def test_only_v4_4_gets_abilities_and_privacy(self) -> None:
        with patch.dict(os.environ, {"AGENT_TOOLS": "true", "TAVILY_API_KEY": "x", "GOOGLE_PLACES_API_KEY": "x"}):
            new, old = self._prompt("v4-4"), self._prompt("v4-3")
        self.assertIn("<what_you_can_do>", new)
        self.assertIn("not end-to-end encrypted", new)
        self.assertIn("You cannot yet set alarms", new)
        self.assertNotIn("<what_you_can_do>", old)
        self.assertNotIn("<privacy>", old)
        # Nothing in the omi block is cut by its size limit.
        self.assertNotIn("...\n</omi>", new)

    def test_a_tool_that_is_off_is_not_offered(self) -> None:
        from agent.context_engine.prompt_engine.modules.omiryn_facts import abilities_block

        with patch.dict(os.environ, {"TAVILY_API_KEY": "", "GOOGLE_PLACES_API_KEY": "", "PROACTIVE_MESSAGING_ENABLED": "false"}):
            block = abilities_block()
        self.assertNotIn("facts on the web", block)
        self.assertNotIn("maps link", block)
        self.assertNotIn("on your own", block)

    def test_someone_new_is_marked_until_omi_knows_them(self) -> None:
        self.assertIn("they are new to you", self._prompt("v4-4"))
        memory = {"source_type": "agent_memories_v3", "title": "Memories", "content": "Has a cat named Biscuit."}
        self.assertNotIn("they are new to you", self._prompt("v4-4", [memory]))
        self.assertNotIn("they are new to you", self._prompt("v4-3"))

    def test_only_v4_5_knows_who_made_it_and_the_app(self) -> None:
        with patch.dict(os.environ, {"AGENT_TOOLS": "true", "TAVILY_API_KEY": "x", "GOOGLE_PLACES_API_KEY": "x"}):
            new, old = self._prompt("v4-5"), self._prompt("v4-4")
        self.assertIn("<who_made_you>", new)
        self.assertIn("never rule one out", new)
        self.assertIn("<the_app>", new)
        self.assertIn("Matches: people you introduce", new)
        # v4-4 is unchanged, and v4-5 keeps all of it.
        self.assertNotIn("<who_made_you>", old)
        self.assertNotIn("<the_app>", old)
        self.assertIn("<privacy>", new)
        self.assertNotIn("...\n</omi>", new)
