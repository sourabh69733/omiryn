"""Rating Omi's replies from the message menu: one rating per message, and it can be undone."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app, current_user
from security.auth import CurrentUser
from storage import list_agent_message_feedback, reset_db

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


if __name__ == "__main__":
    unittest.main()
