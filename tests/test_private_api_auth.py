import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from storage import (
    list_agent_usage_events,
    list_conversations,
    save_agent_message_feedback,
    save_agent_trace,
    save_agent_usage_event,
    save_context_source,
    save_conversation,
    save_draft,
    reset_db,
)


class PrivateApiAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        reset_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_private_apis_reject_anonymous_even_when_auth_required_is_false(self) -> None:
        with patch.dict(os.environ, {"AUTH_REQUIRED": "false"}):
            responses = [
                self.client.post("/api/agent/conversations"),
                self.client.get("/api/agent/conversations"),
                self.client.post("/api/agent-submissions/profile", json={}),
                self.client.get("/api/agent/usage"),
                self.client.get("/api/me/profile"),
            ]

        self.assertTrue(responses)
        for response in responses:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["detail"], "Sign in to continue.")

    def test_public_helper_routes_remain_anonymous(self) -> None:
        with patch.dict(os.environ, {"AUTH_REQUIRED": "false"}):
            response = self.client.get("/api/context-import-prompt")

        self.assertEqual(response.status_code, 200)
        self.assertIn("prompt", response.json())

    def test_private_storage_requires_explicit_user_ownership(self) -> None:
        with self.assertRaises(ValueError):
            save_draft({"id": "draft-a", "status": "draft", "submission": {}})

        with self.assertRaises(ValueError):
            save_conversation({"id": "conversation-a", "status": "active", "messages": []})

        with self.assertRaises(ValueError):
            list_conversations()

        with self.assertRaises(ValueError):
            save_context_source(
                {
                    "conversation_id": "missing-conversation",
                    "source_type": "manual_notes",
                    "title": "Private notes",
                    "content": "private",
                }
            )

        with self.assertRaises(ValueError):
            save_agent_message_feedback(
                {
                    "conversation_id": "conversation-a",
                    "message_index": 0,
                    "rating": "up",
                }
            )

        with self.assertRaises(ValueError):
            save_agent_usage_event(
                {
                    "conversation_id": None,
                    "request_kind": "chat_reply",
                    "provider": "groq",
                    "success": True,
                }
            )

        with self.assertRaises(ValueError):
            save_agent_trace(
                {
                    "conversation_id": "missing-conversation",
                    "turn_index": 0,
                }
            )

        with self.assertRaises(ValueError):
            list_agent_usage_events()

    def test_private_storage_does_not_reassign_existing_owner(self) -> None:
        conversation = {"id": "conversation-a", "status": "active", "messages": []}
        save_conversation(conversation, "user-a")

        with self.assertRaises(ValueError):
            save_conversation(conversation, "user-b")

        draft = {"id": "draft-a", "status": "draft", "submission": {}}
        save_draft(draft, "user-a")

        with self.assertRaises(ValueError):
            save_draft(draft, "user-b")
