"""Uploads become a hidden chat that background memory learns from; deleting the upload undoes it."""

import os
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from agent.memory_engine.processing.context import build_memory_batch
from agent.memory_engine.processing.prompt import memory_batch_prompt
from api.main import app, current_user
from ingestion import upload_chat
from ingestion.upload_chat import whatsapp_upload_messages
from security.auth import CurrentUser
from storage import create_agent_memory, get_conversation, list_agent_memories, list_conversations, reset_db

USER_ID = "upload-user"
EXPORT = """13/09/2026, 9:15 pm - Riya: hey did you see the match
13/09/2026, 9:16 pm - Sourabh: yes!! kohli was insane
13/09/2026, 9:17 pm - Sourabh: i am moving to pune next month btw
14/09/2026, 10:02 am - Riya: <Media omitted>
14/09/2026, 10:05 am - Riya: call me at +91 98765 43210, its riya@example.com
14/09/2026, 10:30 am - Sourabh: will do, i love long drives btw
"""


class UploadMessagesTest(unittest.TestCase):
    def test_the_users_lines_are_theirs_and_everyone_else_is_context(self) -> None:
        messages = whatsapp_upload_messages(EXPORT, "sourabh", ZoneInfo("Asia/Kolkata"))

        self.assertEqual([m["role"] for m in messages], ["other", "user", "other", "user"])
        # A burst within a few minutes is one message, with its real time.
        self.assertIn("moving to pune", messages[1]["content"])
        self.assertEqual(messages[1]["created_at"], "2026-09-13T21:17:00+05:30")
        self.assertEqual(messages[0]["speaker"], "Riya")
        # Phone numbers and emails are masked; media placeholders are dropped.
        self.assertNotIn("98765", messages[2]["content"])
        self.assertNotIn("riya@example.com", messages[2]["content"])
        self.assertTrue(all(m["imported"] for m in messages))

    def test_a_us_style_date_is_read_month_first(self) -> None:
        export = "9/13/26, 9:15 PM - Sourabh: hello there friend\n9/14/26, 9:15 AM - Riya: hi"
        self.assertTrue(whatsapp_upload_messages(export, "sourabh", ZoneInfo("UTC"))[0]["created_at"].startswith("2026-09-13T21:15"))

    def test_the_whole_chat_is_kept_up_to_the_newest_limit(self) -> None:
        lines = [f"0{day}/02/2026, {hour:02d}:00 - {'Me' if hour % 2 else 'Riya'}: line {day}-{hour}" for day in range(1, 10) for hour in range(1, 13)]
        kept = whatsapp_upload_messages("\n".join(lines), "me", ZoneInfo("UTC"))
        self.assertEqual(len(kept), 108)  # nothing cut: months-old lines stay searchable
        with patch.object(upload_chat, "MAX_UPLOAD_MESSAGES", 10):
            newest = whatsapp_upload_messages("\n".join(lines), "me", ZoneInfo("UTC"))
        self.assertEqual([m["content"] for m in newest][-1], "line 9-12")
        self.assertLessEqual(len(newest), 11)  # the limit, plus the line the first kept reply answers

    def test_background_memory_sees_who_said_it(self) -> None:
        messages = whatsapp_upload_messages(EXPORT, "sourabh", ZoneInfo("Asia/Kolkata"))
        batch = build_memory_batch(conversation_id="c", user_id="u", messages=messages)
        import json

        payload = json.loads(memory_batch_prompt(batch, []))["messages"]
        self.assertEqual(payload[0]["speaker"], "Riya")
        self.assertTrue(payload[0]["from_upload"])
        self.assertFalse(payload[0]["evidence_eligible"])
        self.assertTrue(payload[1]["evidence_eligible"])


class UploadRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock", "DATA_POINT_EXTRACTOR": "off"})
        self.env.start()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="u@example.com", display_name="U")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)
        self.chat = self.client.post("/api/agent/conversations").json()["id"]

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def _upload(self):
        with patch("agent.cognition.background.uploads.request_flush_now") as flush:
            response = self.client.post(
                f"/api/agent/conversations/{self.chat}/whatsapp-import",
                json={"title": "Riya", "content": EXPORT, "user_sender": "Sourabh"},
            )
        return response, flush

    def _upload_chats(self) -> list[dict]:
        return [c for c in list_conversations(USER_ID) if c.get("import_source_id")]

    def test_an_upload_starts_learning_and_stays_out_of_history(self) -> None:
        response, flush = self._upload()

        self.assertEqual(response.status_code, 201)
        [upload_chat] = self._upload_chats()
        self.assertEqual(upload_chat["import_source_id"], response.json()["id"])
        flush.assert_called_once_with(upload_chat["id"], USER_ID)
        listed = [c["id"] for c in self.client.get("/api/agent/conversations").json()["conversations"]]
        self.assertEqual(listed, [self.chat])
        refused = self.client.post(f"/api/agent/conversations/{upload_chat['id']}/messages", json={"message": "hi"})
        self.assertEqual(refused.status_code, 409)

    def test_deleting_the_upload_deletes_what_it_taught(self) -> None:
        response, _ = self._upload()
        [upload_chat] = self._upload_chats()
        create_agent_memory(
            {
                "user_id": USER_ID, "kind": "semantic", "purposes": ["personalization"], "key": "drives",
                "value": "Loves long drives.", "statement": "Loves long drives.",
                "evidence": [{"conversation_id": upload_chat["id"], "message_index": 3, "exact_quote": "i love long drives", "observed_at": "2026-09-14T05:00:00+00:00"}],
            }
        )
        memories = self.client.get("/api/me/memories").json()["memories"]
        self.assertTrue(memories[0]["from_upload"])

        self.client.delete(f"/api/me/context-sources/{response.json()['id']}")

        self.assertIsNone(get_conversation(upload_chat["id"], USER_ID))
        self.assertEqual(list_agent_memories(USER_ID), [])


if __name__ == "__main__":
    unittest.main()
