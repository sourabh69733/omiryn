import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from api.main import app
from storage import (
    ENGINE,
    PRIVATE_USER_OWNED_TABLE_NAMES,
    list_agent_usage_events,
    list_conversations,
    private_data_ownership_violations,
    save_agent_message_feedback,
    save_agent_trace,
    save_agent_usage_event,
    save_context_source,
    save_conversation,
    save_data_point_extraction_debug,
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

        with self.assertRaises(ValueError):
            save_data_point_extraction_debug(
                {
                    "source_kind": "agent_conversation",
                    "decision": "approved",
                    "candidate": {},
                    "review": {},
                }
            )

    def test_private_storage_does_not_reassign_existing_owner(self) -> None:
        conversation = {"id": "conversation-a", "status": "active", "messages": []}
        save_conversation(conversation, "user-a")

        with self.assertRaises(ValueError):
            save_conversation(conversation, "user-b")

        draft = {"id": "draft-a", "status": "draft", "submission": {}}
        save_draft(draft, "user-a")

        with self.assertRaises(ValueError):
            save_draft(draft, "user-b")

    def test_private_user_owned_tables_have_non_nullable_user_id(self) -> None:
        inspector = inspect(ENGINE)
        for table_name in PRIVATE_USER_OWNED_TABLE_NAMES:
            columns = {
                column["name"]: column
                for column in inspector.get_columns(table_name)
            }
            self.assertIn("user_id", columns, table_name)
            self.assertFalse(columns["user_id"]["nullable"], table_name)

    def test_private_data_ownership_audit_is_clean_after_reset(self) -> None:
        self.assertEqual(private_data_ownership_violations(), {})
