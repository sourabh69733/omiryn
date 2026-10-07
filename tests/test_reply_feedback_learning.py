"""Omi learns how to talk from the user: rated replies shape the next one; requests save at once."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.context_engine.assembly.sources import _reply_feedback_sources
from agent.feedback import normalize_message_feedback
from agent.runtime.orchestrator import run_agent_turn
from api.main import app, current_user
from security.auth import CurrentUser
from storage import reset_db, save_agent_message_feedback, save_conversation

USER_ID = "feedback-user"
CHAT = "feedback-chat"
MESSAGES = [
    {"role": "user", "content": "kuch nhi"},
    {"role": "assistant", "content": "Sahi hai, kabhi kabhi kuch nahi karna hi best plan hota hai."},
    {"role": "user", "content": "hmm"},
    {"role": "assistant", "content": "Old film tonight? You loved the last one."},
]


def _rate(index: int, rating: str, reasons: list[str] = (), comment: str = "") -> None:
    save_agent_message_feedback(
        normalize_message_feedback(
            {
                "conversation_id": CHAT,
                "user_id": USER_ID,
                "message_index": index,
                "rating": rating,
                "comment": comment,
                "metadata": {"reasons": list(reasons)},
            }
        )
    )


class RatedRepliesTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CHAT, "status": "active", "messages": MESSAGES}, USER_ID)

    def test_disliked_and_liked_replies_reach_the_prompt_with_the_reason(self) -> None:
        _rate(1, "bad", ["too_much"], "robotic")
        _rate(3, "good")

        [source] = _reply_feedback_sources(USER_ID)

        self.assertIn('They disliked:\n- "Sahi hai, kabhi kabhi', source["content"])
        self.assertIn("(too much; robotic)", source["content"])
        self.assertIn('They liked:\n- "Old film tonight?', source["content"])
        self.assertIn("never repeat these lines", source["content"])

    def test_no_ratings_no_block(self) -> None:
        self.assertEqual(_reply_feedback_sources(USER_ID), [])


class SaveRequestsNowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock", "DATA_POINT_EXTRACTOR": "rules", "AGENT_PIPELINE_VERSION": "v3"},
        )
        self.env.start()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="f@example.com", display_name="F")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)
        self.conversation_id = self.client.post("/api/agent/conversations").json()["id"]

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def _send(self, text: str):
        with patch("api.main.run_agent_turn", run_agent_turn), patch(
            "api.routes.conversations.request_flush_now"
        ) as flush:
            self.client.post(f"/api/agent/conversations/{self.conversation_id}/messages", json={"message": text})
        return flush

    def test_a_how_to_talk_request_is_saved_right_away(self) -> None:
        self.assertTrue(self._send("bas suno, sawal mat puchna please").called)

    def test_an_ordinary_message_waits_for_the_idle_flush(self) -> None:
        self.assertFalse(self._send("I watched a film today").called)


if __name__ == "__main__":
    unittest.main()
