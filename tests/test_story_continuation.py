import os
import unittest
from unittest.mock import patch

from agent.context_engine.conversation_engine.understanding.rules import continues_story
from agent.context_engine.engine import build_model_context_package
from agent.providers.shared.config import CHAT_REPLY_WORD_LIMIT
from agent.providers.shared.messages import _chat_reply_word_limit
from agent.runtime.orchestrator import _turn_notes
from storage import reset_db, save_conversation

STORY = [
    {"role": "user", "content": "tell me a story about a chai stall owner"},
    {"role": "assistant", "content": "Raju ran a chai stall near Dadar station.", "story": True},
    {"role": "assistant", "content": "One rainy night a stranger left a bag behind.", "story": True},
]


class ContinuesStoryTest(unittest.TestCase):
    def test_short_reactions_keep_the_story_going(self) -> None:
        for text in ("then?", "wow", "aage kya hua", "haha and then what", "", "ok"):
            with self.subTest(text=text):
                self.assertTrue(continues_story(text, STORY))

    def test_long_message_with_a_continue_phrase_keeps_it_going(self) -> None:
        self.assertTrue(
            continues_story("this is so good, I really want to know what happened to the bag", STORY)
        )

    def test_stop_words_and_new_long_topics_end_it(self) -> None:
        self.assertFalse(continues_story("ok enough, bye", STORY))
        self.assertFalse(
            continues_story("btw I had a really long day at work and my manager was annoying", STORY)
        )

    def test_no_story_running(self) -> None:
        chat = [{"role": "assistant", "content": "hey, how's it going?"}]
        self.assertFalse(continues_story("then?", chat))
        self.assertFalse(continues_story("then?", []))


class StoryContinuationContextTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def _package(self, messages: list[dict], user_text: str):
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
            )

    def test_follow_up_mid_story_is_a_story_turn(self) -> None:
        package = self._package(STORY, "then?")
        self.assertIn("story_continuation", package.query_intent.labels)
        self.assertIn("story_or_long_reply", package.query_intent.labels)
        self.assertEqual(package.question_limit, 1)

    def test_same_words_without_a_story_are_normal_chat(self) -> None:
        package = self._package([{"role": "assistant", "content": "hey!"}], "then?")
        self.assertNotIn("story_or_long_reply", package.query_intent.labels)


class StoryNoteTest(unittest.TestCase):
    def test_follow_up_gets_the_continue_note(self) -> None:
        [note] = _turn_notes(1, ("story_or_long_reply", "story_continuation"))
        self.assertIn("continue the story from where it stopped", note["content"])
        [note] = _turn_notes(1, ("story_or_long_reply",))
        self.assertIn("the user asked for a story", note["content"])

    def test_story_note_lifts_the_one_bubble_word_cap(self) -> None:
        [note] = _turn_notes(1, ("story_or_long_reply", "story_continuation"))
        messages = [{"role": "user", "content": "then?"}, note]
        self.assertGreater(_chat_reply_word_limit(messages), CHAT_REPLY_WORD_LIMIT)
        self.assertEqual(
            _chat_reply_word_limit([{"role": "user", "content": "then?"}]), CHAT_REPLY_WORD_LIMIT
        )


if __name__ == "__main__":
    unittest.main()
