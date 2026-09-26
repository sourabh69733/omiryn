"""After a break the companion knows where the previous session stopped."""

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from agent.context_engine.assembly.sources import build_reply_context_sources
from agent.providers.shared.messages import reply_window
from agent.shared.clock import frozen_time
from agent.shared.timeline import previous_session
from storage import reset_db, save_conversation, set_user_timezone

USER_ID = "last-session-user"
CONVERSATION_ID = "last-session-conversation"
FRIDAY = "2026-09-25T11:58:00+00:00"  # 5:28 pm in India
NUDGE = "2026-09-25T15:46:00+00:00"
NOW = datetime(2026, 9, 26, 6, 10, tzinfo=UTC)  # 11:40 am in India, next day
CHAT = [
    {"role": "user", "content": "I'm from Jaipur", "created_at": "2026-09-24T10:00:00+00:00"},
    {"role": "assistant", "content": "Pink city!", "created_at": "2026-09-24T10:00:10+00:00"},
    {"role": "user", "content": "tell some nice crime story", "created_at": FRIDAY},
    {"role": "assistant", "content": "Detective Siya took a murder case.", "story": True, "created_at": FRIDAY},
    {"role": "assistant", "content": "The killer was her own brother.", "story": True, "created_at": FRIDAY},
    {"role": "assistant", "content": "kya Jaipur mein rehna accha laga?", "proactive": True, "created_at": NUDGE},
]


class PreviousSessionTest(unittest.TestCase):
    def test_finds_the_session_before_now(self) -> None:
        self.assertEqual([m["content"] for m in previous_session(CHAT, NOW)][:1], ["tell some nice crime story"])

    def test_mid_session_the_previous_one_is_the_session_before(self) -> None:
        same_evening = datetime(2026, 9, 25, 16, 0, tzinfo=UTC)
        self.assertEqual(previous_session(CHAT, same_evening), CHAT[:2])

    def test_no_previous_session_in_a_first_session(self) -> None:
        self.assertEqual(previous_session(CHAT[2:], datetime(2026, 9, 25, 16, 0, tzinfo=UTC)), [])


class LastSessionContextTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": CHAT}, USER_ID)
        set_user_timezone(USER_ID, "Asia/Kolkata")

    def _block(self, now: datetime) -> str:
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}), frozen_time(now):
            sources = build_reply_context_sources(CONVERSATION_ID, None, "what were we doing last time?", USER_ID)
        return next((s["content"] for s in sources if s["source_type"] == "last_session"), "")

    def test_names_the_story_not_the_unanswered_nudge(self) -> None:
        block = self._block(NOW)
        self.assertIn("the previous session ended Friday 25 Sep, 5:28 pm (18 hours ago)", block)
        self.assertIn('- them: "tell some nice crime story"', block)
        self.assertIn('- you: "Detective Siya took a murder case. The killer was her own brother."', block)
        self.assertIn("in the middle of telling a story; it was not finished", block)
        self.assertIn("they have not answered it, so it was not the topic", block)
        self.assertNotIn("Pink city", block)  # an older session

    def test_no_block_in_a_first_session(self) -> None:
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": CHAT[2:5]}, USER_ID)
        self.assertEqual(self._block(datetime(2026, 9, 25, 12, 5, tzinfo=UTC)), "")


class ReturnHistoryTest(unittest.TestCase):
    def test_story_stays_in_the_chat_history_after_the_break(self) -> None:
        messages = [*CHAT, {"role": "user", "content": "hey hi", "created_at": NOW.isoformat()}]
        window = reply_window(messages, summarized_through=5)
        contents = [m["content"] for m in window]
        self.assertIn("Detective Siya took a murder case.", contents)
        self.assertNotIn("I'm from Jaipur", contents)


if __name__ == "__main__":
    unittest.main()
