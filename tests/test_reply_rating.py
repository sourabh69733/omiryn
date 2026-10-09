"""Rating Omi's replies from the message menu: one rating per message, and it can be undone."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app, current_user
from security.auth import CurrentUser
from storage import list_agent_memories, list_agent_message_feedback, reset_db, save_conversation

USER_ID = "rating-user"


class ReplyRatingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock"})
        self.env.start()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="r@example.com", display_name="R")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)
        self.chat = self.client.post("/api/agent/conversations").json()["id"]
        self.url = f"/api/agent/conversations/{self.chat}/messages/0/feedback"

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def test_a_new_rating_replaces_the_old_one(self) -> None:
        self.client.post(self.url, json={"rating": "good"})
        self.client.post(self.url, json={"rating": "bad", "reasons": ["too_much"]})

        [rating] = list_agent_message_feedback(self.chat, USER_ID)
        self.assertEqual((rating["rating"], rating["metadata"]["reasons"]), ("bad", ["too_much"]))

    def test_a_rating_can_be_undone(self) -> None:
        self.client.post(self.url, json={"rating": "good"})

        self.assertEqual(self.client.delete(self.url).json()["cleared"], 1)
        self.assertEqual(list_agent_message_feedback(self.chat, USER_ID), [])


    def _rate(self, index: int, reasons: list[str]) -> None:
        self.client.post(f"/api/agent/conversations/{self.chat}/messages/{index}/feedback", json={"rating": "bad", "reasons": reasons})

    def _rating_memories(self) -> list[dict]:
        return [m for m in list_agent_memories(USER_ID) if m.get("extractor") == "reply_ratings"]

    def test_the_same_reason_twice_becomes_a_lasting_how_to_talk_memory(self) -> None:
        self._add_replies()
        self._rate(1, ["too_much"])
        self.assertEqual(self._rating_memories(), [])
        self._rate(3, ["too_much"])

        [memory] = self._rating_memories()
        self.assertEqual(memory["kind"], "procedural")
        self.assertIn("too long", memory["statement"])
        self.assertEqual(sorted(e["message_index"] for e in memory["evidence"]), [1, 3])

        # Undoing one rating drops it below the threshold, so the memory goes.
        self.client.delete(f"/api/agent/conversations/{self.chat}/messages/3/feedback")
        self.assertEqual(self._rating_memories(), [])

    def test_different_reasons_do_not_add_up(self) -> None:
        self._add_replies()
        self._rate(1, ["too_much"])
        self._rate(3, ["bad_tone"])
        self.assertEqual(self._rating_memories(), [])

    def _add_replies(self) -> None:
        messages = [
            {"role": "assistant", "content": "Hi!", "created_at": "2026-10-09T10:00:00+00:00"},
            {"role": "assistant", "content": "A very long reply " * 20, "created_at": "2026-10-09T10:00:05+00:00"},
            {"role": "user", "content": "ok", "created_at": "2026-10-09T10:01:00+00:00"},
            {"role": "assistant", "content": "Another long reply " * 20, "created_at": "2026-10-09T10:01:05+00:00"},
        ]
        save_conversation({"id": self.chat, "status": "active", "messages": messages}, USER_ID)


if __name__ == "__main__":
    unittest.main()
