"""Replies see uploaded chats: an index line always, more when the message names the person or a topic."""

import unittest

from agent.context_engine.assembly.uploaded_chats import matching_topics, uploaded_chat_sources
from agent.context_engine.prompt_engine.blocks import _grouped_sources
from storage import reset_db, save_conversation
from storage.upload_digests import save_upload_digest

USER_ID = "shared-chats-user"
MESSAGES = [
    {"role": "other", "speaker": "Farheen", "content": "my lead changed the spec again"},
    {"role": "user", "content": "8th review cycle on the same task, never ending"},
    {"role": "user", "content": "finance influencers are clowns, never trust them"},
    {"role": "other", "speaker": "Farheen", "content": "some of them are fine yaar"},
]
DIGEST = {
    "chat_with": "Farheen",
    "chat_dates": {"from": "2026-10-15", "to": "2026-10-21"},
    "summary": "Two colleagues venting about review work and money.",
    "index_line": "review cycles, finance influencers",
    "threads": [
        {"title": "Endless review cycles", "summary": "Both stuck in long reviews.", "user_view": "Frustrated.", "other_view": "Specs keep changing.", "lines": [0, 1], "started": "2026-10-15"},
        {"title": "Finance influencers", "summary": "User distrusts finance influencers; Farheen thinks some are fine.", "lines": [2, 3], "started": "2026-10-16"},
    ],
    "person": [{"text": "Her lead keeps changing specs.", "lines": [0]}],
    "plans": [{"what": "Wait for the new task sheet", "when": None, "lines": [1]}],
}


class SharedChatsContextTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": "hidden", "status": "active", "import_source_id": "src-1", "messages": MESSAGES}, USER_ID)
        save_upload_digest("src-1", USER_ID, "hidden", "Farheen", DIGEST)

    def _content(self, text: str) -> str:
        [source] = uploaded_chat_sources(USER_ID, text)
        return source["content"]

    def test_every_reply_knows_the_chat_exists_and_nothing_more(self) -> None:
        content = self._content("kya chal raha hai")
        self.assertIn("Farheen (2026-10-15 to 2026-10-21): review cycles, finance influencers", content)
        self.assertNotIn("Summary:", content)
        self.assertNotIn("Lines from the chat", content)

    def test_naming_the_person_brings_the_chat_and_real_lines(self) -> None:
        content = self._content("farheen ke baare mein kya pata hai?")
        self.assertIn("Summary: Two colleagues venting", content)
        self.assertIn("About Farheen: Her lead keeps changing specs.", content)
        self.assertIn("Plans mentioned: Wait for the new task sheet", content)
        self.assertIn('Farheen: "my lead changed the spec again"', content)

    def test_a_topic_brings_its_summary_and_both_sides(self) -> None:
        content = self._content("what did we say about finance influencers")
        self.assertIn("Finance influencers [2026-10-16]", content)
        self.assertIn('User: "finance influencers are clowns, never trust them"', content)
        self.assertIn('Farheen: "some of them are fine yaar"', content)
        self.assertNotIn("Endless review cycles", content)

    def test_no_uploads_no_block(self) -> None:
        self.assertEqual(uploaded_chat_sources("someone-else", "farheen?"), [])

    def test_it_has_its_own_block_in_the_prompt(self) -> None:
        self.assertIn("shared_chats", _grouped_sources(uploaded_chat_sources(USER_ID, "hi")))

    def test_small_talk_matches_no_topic(self) -> None:
        self.assertEqual(matching_topics(DIGEST["threads"], "hi how are you"), [])


if __name__ == "__main__":
    unittest.main()
