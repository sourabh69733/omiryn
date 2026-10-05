"""A chat can be archived: it keeps its messages, leaves the main list and gets no proactive messages."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.proactive import service as proactive
from agent.runtime.orchestrator import run_agent_turn
from api.main import app, current_user
from security.auth import CurrentUser
from storage import get_conversation, reset_db

USER_ID = "archive-user"


class ConversationArchiveApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock", "DATA_POINT_EXTRACTOR": "rules",
             "AGENT_PIPELINE_VERSION": "v1", "AGENT_ROLLOUT": "off"},
        )
        self.env.start()
        app.dependency_overrides.clear()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="archive@example.com", display_name="Archive User")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)
        self.conversation_id = self.client.post("/api/agent/conversations").json()["id"]

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def _archive(self, archived: bool, conversation_id: str | None = None):
        return self.client.patch(
            f"/api/agent/conversations/{conversation_id or self.conversation_id}/archive",
            json={"archived": archived},
        )

    def _summary(self) -> dict:
        rows = self.client.get("/api/agent/conversations").json()["conversations"]
        return next(row for row in rows if row["id"] == self.conversation_id)

    def test_archive_and_unarchive(self) -> None:
        before = self._summary()
        self.assertIsNone(before["archived_at"])

        response = self._archive(True)

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["archived_at"])
        after = self._summary()
        self.assertIsNotNone(after["archived_at"])
        self.assertEqual(after["updated_at"], before["updated_at"])
        self.assertEqual(after["message_count"], before["message_count"])

        self.assertIsNone(self._archive(False).json()["archived_at"])
        self.assertIsNone(self._summary()["archived_at"])

    def test_unknown_chat_is_404(self) -> None:
        self.assertEqual(self._archive(True, "missing").status_code, 404)

    def test_sending_a_message_brings_it_back(self) -> None:
        self._archive(True)

        with patch("api.main.run_agent_turn", run_agent_turn):
            response = self.client.post(
                f"/api/agent/conversations/{self.conversation_id}/messages", json={"message": "hey, back again"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._summary()["archived_at"])

    def test_no_proactive_messages_in_an_archived_chat(self) -> None:
        with patch.object(proactive, "proactive_messaging_enabled", return_value=True), patch.object(
            proactive, "get_proactive_enabled", return_value=True
        ):
            self.assertIsNotNone(proactive._open_conversation(USER_ID, self.conversation_id))
            self._archive(True)
            self.assertIsNone(proactive._open_conversation(USER_ID, self.conversation_id))
        self.assertIsNotNone(get_conversation(self.conversation_id, USER_ID)["archived_at"])


if __name__ == "__main__":
    unittest.main()
