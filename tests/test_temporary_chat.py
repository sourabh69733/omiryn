"""Temporary Chat: Omi replies as usual but learns nothing, and the chat is deleted when stale."""

import asyncio
import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import update

from agent.cognition.background.idle import catch_up_pending, run_memory_flush_job
from agent.cognition.background.service import run_background_cognition
from agent.runtime.orchestrator import run_agent_turn
from api.main import app, current_user
from security.auth import CurrentUser
from agent.shared.clock import utc_now
from storage import (
    delete_stale_temporary_conversations,
    get_conversation,
    is_temporary_conversation,
    reset_db,
)
from storage.database import ENGINE
from storage.schema import agent_conversations

USER_ID = "temporary-user"


class TemporaryChatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock", "DATA_POINT_EXTRACTOR": "rules", "AGENT_PIPELINE_VERSION": "v3"},
        )
        self.env.start()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="t@example.com", display_name="T")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)
        self.main = self.client.post("/api/agent/conversations").json()["id"]
        created = self.client.post("/api/agent/conversations", json={"temporary": True}).json()
        self.temp = created["id"]
        self.assertTrue(created["temporary"])

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def _send(self, chat: str, text: str):
        with patch("api.main.run_agent_turn", run_agent_turn), patch(
            "api.routes.conversations.schedule_idle_flush"
        ) as idle, patch("api.routes.conversations.request_flush_now") as now:
            response = self.client.post(f"/api/agent/conversations/{chat}/messages", json={"message": text})
        return response, idle, now

    def test_omi_replies_but_no_learning_is_scheduled(self) -> None:
        response, idle, now = self._send(self.temp, "I live in Pune and I hate small talk. No questions please.")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_conversation(self.temp, USER_ID)["messages"][-1]["role"], "assistant")
        idle.assert_not_called()
        now.assert_not_called()

    def test_background_runs_refuse_a_temporary_chat(self) -> None:
        self._send(self.temp, "I live in Pune.")
        messages = get_conversation(self.temp, USER_ID)["messages"]

        result = asyncio.run(run_background_cognition(self.temp, USER_ID, messages))
        self.assertEqual(result["status"], "temporary_chat")
        job = asyncio.run(run_memory_flush_job({"conversation_id": self.temp, "user_id": USER_ID}))
        self.assertEqual(job["status"], "temporary_chat")
        with patch("agent.cognition.background.idle.background_cognition_enabled", return_value=True):
            self.assertNotIn(self.temp, catch_up_pending(USER_ID))

    def test_it_stays_out_of_history_and_cannot_be_rated(self) -> None:
        listed = [c["id"] for c in self.client.get("/api/agent/conversations").json()["conversations"]]
        self.assertEqual(listed, [self.main])
        rating = self.client.post(f"/api/agent/conversations/{self.temp}/messages/0/feedback", json={"rating": "good"})
        self.assertEqual(rating.status_code, 400)

    def test_a_normal_chat_never_turns_temporary(self) -> None:
        self.assertFalse(is_temporary_conversation(self.main, USER_ID))
        self.assertTrue(is_temporary_conversation(self.temp, USER_ID))

    def test_a_stale_temporary_chat_is_deleted_and_the_main_chat_kept(self) -> None:
        self.assertEqual(delete_stale_temporary_conversations(USER_ID), 0)
        with ENGINE.begin() as connection:
            connection.execute(
                update(agent_conversations).values(updated_at=utc_now() - timedelta(hours=25))
            )

        self.assertEqual(delete_stale_temporary_conversations(USER_ID), 1)
        self.assertIsNone(get_conversation(self.temp, USER_ID))
        self.assertIsNotNone(get_conversation(self.main, USER_ID))


if __name__ == "__main__":
    unittest.main()
