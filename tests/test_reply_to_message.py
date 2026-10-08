"""Replying to a message: the bubble keeps a short quote and Omi is told what is meant."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.providers.shared.messages import _provider_messages
from agent.runtime.orchestrator import run_agent_turn
from api.main import app, current_user
from security.auth import CurrentUser
from storage import delete_conversation_messages, get_conversation, reset_db

USER_ID = "reply-user"


class ReplyToMessageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock", "DATA_POINT_EXTRACTOR": "rules", "AGENT_PIPELINE_VERSION": "v3"},
        )
        self.env.start()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="r@example.com", display_name="R")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)
        self.chat = self.client.post("/api/agent/conversations").json()["id"]
        self._send("Protests are common in India, right?")

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def _send(self, text: str, reply_to: int | None = None):
        body = {"message": text, **({"reply_to_index": reply_to} if reply_to is not None else {})}
        with patch("api.main.run_agent_turn", run_agent_turn):
            return self.client.post(f"/api/agent/conversations/{self.chat}/messages", json=body)

    def _messages(self) -> list[dict]:
        return get_conversation(self.chat, USER_ID)["messages"]

    def test_the_reply_keeps_a_quote_and_the_model_sees_it(self) -> None:
        omi_index = max(i for i, m in enumerate(self._messages()) if m["role"] == "assistant")
        omi_text = self._messages()[omi_index]["content"]

        self.assertEqual(self._send("Explain this part?", omi_index).status_code, 200)

        sent = next(m for m in self._messages() if m.get("content") == "Explain this part?")
        self.assertEqual(sent["reply_to"]["index"], omi_index)
        self.assertEqual(sent["reply_to"]["role"], "assistant")
        rendered = _provider_messages([sent])[0]["content"]
        self.assertIn("Replying to your message:", rendered)
        self.assertIn(omi_text[:20], rendered)

    def test_a_missing_or_deleted_message_cannot_be_quoted(self) -> None:
        self.assertEqual(self._send("what?", 99).status_code, 400)
        delete_conversation_messages(USER_ID, self.chat, [0])
        self.assertEqual(self._send("what?", 0).status_code, 400)

    def test_deleting_the_quoted_message_removes_its_quote(self) -> None:
        self._send("I meant this one", 0)
        delete_conversation_messages(USER_ID, self.chat, [0])

        reply = next(m for m in self._messages() if m.get("content") == "I meant this one")
        self.assertEqual(reply["reply_to"], {"index": 0, "deleted": True})
        self.assertIn("they later deleted", _provider_messages([reply])[0]["content"])


if __name__ == "__main__":
    unittest.main()
