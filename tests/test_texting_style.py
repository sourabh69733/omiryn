"""How the user texts, measured from their own uploaded lines, reaches every chat."""

import unittest

from agent.context_engine.sources.texting_style import texting_style_sources as _texting_style_sources
from agent.context_engine.conversation_engine.personalization import texting_style_note
from storage import reset_db, save_conversation
from storage.context_sources import save_whatsapp_import_bundle

USER_ID = "texting-style-user"
SHORT_LOWERCASE = {
    "average_words": 5.6,
    "short_message_share": "72%",
    "lowercase_opening_share": "80%",
    "question_share": "3%",
    "exclamation_share": "4%",
}


class TextingStyleNoteTest(unittest.TestCase):
    def test_note_says_what_the_numbers_show(self) -> None:
        note = texting_style_note(SHORT_LOWERCASE)
        self.assertIn("about 6 words per message", note)
        self.assertIn("mostly quick short lines", note)
        self.assertIn("usually starting in lowercase", note)
        self.assertIn("rarely asking questions", note)
        self.assertIn("not a request", note)
        self.assertNotIn("emoji", note)

    def test_no_numbers_no_note(self) -> None:
        self.assertIsNone(texting_style_note({}))


class TextingStyleSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        for chat in ("upload-chat", "other-chat"):
            save_conversation({"id": chat, "status": "active", "messages": []}, USER_ID)

    def _upload(self, style_kind: str, source_id: str) -> None:
        save_whatsapp_import_bundle(
            {
                "conversation_id": "upload-chat",
                "context_source_id": source_id,
                "style_kind": style_kind,
                "title": "Chat",
                "selected_sender": "Sourabh",
                "style_profiles": [
                    {"sender": "Sourabh", "summary": SHORT_LOWERCASE, "sample_messages": [], "metadata": {}},
                    {"sender": "Aarav", "summary": {"average_words": 20}, "sample_messages": [], "metadata": {}},
                ],
            },
            USER_ID,
        )

    def test_their_own_upload_gives_a_note_for_every_chat(self) -> None:
        self._upload("user_style", "source-1")
        [source] = _texting_style_sources(USER_ID)
        self.assertEqual(source["source_type"], "texting_style")
        self.assertIn("about 6 words per message", source["content"])

    def test_a_friend_style_import_is_not_how_they_text(self) -> None:
        self._upload("friend_style", "source-2")
        self.assertEqual(_texting_style_sources(USER_ID), [])


if __name__ == "__main__":
    unittest.main()
