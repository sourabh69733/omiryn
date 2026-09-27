"""A message whose reply fails is kept, marked failed, and can be retried."""

import asyncio
import os
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from agent.providers.companion.service import generate_agent_reply, reply_fallback_model
from agent.runtime.orchestrator import run_agent_turn
from agent.shared.clock import utc_now
from api.main import app, current_user
from security.auth import CurrentUser
from storage import get_conversation, reset_db, save_conversation

USER_ID = "test-user"


class ReplyFailureApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock", "DATA_POINT_EXTRACTOR": "rules",
             "AGENT_PIPELINE_VERSION": "v1", "AGENT_ROLLOUT": "off"},
        )
        self.env.start()
        app.dependency_overrides.clear()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="test@example.com", display_name="Test User")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)
        self.conversation_id = self.client.post("/api/agent/conversations").json()["id"]

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def _send(self, text: str, turn=None):
        with patch("api.main.run_agent_turn", turn or run_agent_turn):
            return self.client.post(
                f"/api/agent/conversations/{self.conversation_id}/messages", json={"message": text}
            )

    def _retry(self, index: int, turn=None):
        with patch("api.main.run_agent_turn", turn or run_agent_turn):
            return self.client.post(f"/api/agent/conversations/{self.conversation_id}/messages/{index}/retry")

    def _messages(self) -> list[dict]:
        return get_conversation(self.conversation_id, USER_ID)["messages"]

    def test_failed_reply_keeps_the_message_marked_failed(self) -> None:
        response = self._send("hi, what is next now?", AsyncMock(side_effect=httpx.ReadTimeout("slow")))

        self.assertEqual(response.status_code, 502)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "reply_failed")
        last = self._messages()[-1]
        self.assertEqual(detail["message_index"], len(self._messages()) - 1)
        self.assertEqual((last["content"], last["delivery_status"]), ("hi, what is next now?", "failed"))

    def test_retry_replies_and_keeps_the_original_send_time(self) -> None:
        self._send("hi, what is next now?", AsyncMock(side_effect=httpx.ReadTimeout("slow")))
        index = len(self._messages()) - 1
        sent_at = self._messages()[index]["created_at"]

        response = self._retry(index)

        self.assertEqual(response.status_code, 200)
        messages = self._messages()
        self.assertEqual(messages[index]["delivery_status"], "read")
        self.assertEqual(messages[index]["created_at"], sent_at)
        self.assertEqual(messages[index + 1]["role"], "assistant")

    def test_retry_is_refused_when_there_is_nothing_to_retry(self) -> None:
        self._send("hello there")
        answered = next(i for i, m in enumerate(self._messages()) if m["role"] == "user")
        self.assertEqual(self._retry(answered).status_code, 409)
        self.assertEqual(self._retry(99).status_code, 409)

    def test_a_new_message_answers_for_the_failed_one(self) -> None:
        self._send("first thing", AsyncMock(side_effect=httpx.ReadTimeout("slow")))
        turn = AsyncMock(wraps=run_agent_turn)

        self.assertEqual(self._send("second thing", turn).status_code, 200)

        sent_history = turn.await_args.kwargs["messages"]
        self.assertEqual(sent_history[-1]["content"], "first thing")
        self.assertNotIn("failed", {m.get("delivery_status") for m in self._messages()})

    def test_a_reply_lost_mid_flight_can_be_retried(self) -> None:
        conversation = get_conversation(self.conversation_id, USER_ID)
        stale = (utc_now() - timedelta(minutes=5)).isoformat()
        conversation["messages"].append(
            {"role": "user", "content": "anyone?", "created_at": stale, "delivery_status": "sending"}
        )
        save_conversation(conversation, USER_ID)
        self.assertEqual(self._retry(len(conversation["messages"]) - 1).status_code, 200)


class ReplyFallbackTest(unittest.TestCase):
    def test_fallback_is_a_known_fast_model(self) -> None:
        with patch.dict(os.environ, {"AGENT_REPLY_FALLBACK_MODEL": ""}):
            self.assertEqual(
                reply_fallback_model("deepinfra", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
                "meta-llama/Llama-3.1-70B-Instruct-Turbo",
            )
            self.assertIsNone(reply_fallback_model("deepinfra", "meta-llama/Llama-3.1-70B-Instruct-Turbo"))
            self.assertIsNone(reply_fallback_model("groq", "some-model"))
        with patch.dict(os.environ, {"AGENT_REPLY_FALLBACK_MODEL": "off"}):
            self.assertIsNone(reply_fallback_model("deepinfra", None))

    def test_a_timeout_is_retried_once_on_the_fallback_model(self) -> None:
        chat = AsyncMock(side_effect=[httpx.ReadTimeout("slow"), "hey!"])
        with patch.dict(os.environ, {"AGENT_PROVIDER": "deepinfra", "AGENT_REPLY_FALLBACK_MODEL": "backup-model"}), patch(
            "agent.providers.companion.service.provider_chat", chat
        ):
            reply = asyncio.run(generate_agent_reply([{"role": "user", "content": "hi there friend"}], system_prompt="S"))
        self.assertEqual(reply, "hey!")
        self.assertEqual(chat.await_args_list[1].kwargs["model"], "backup-model")
        self.assertEqual(chat.await_args_list[0].kwargs["timeout_seconds"], 25.0)


if __name__ == "__main__":
    unittest.main()
