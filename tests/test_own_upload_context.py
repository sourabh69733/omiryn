"""In v3 the user's own uploaded chat reaches replies through shared_chats and search, not old chunks."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.context_engine.assembly.sources import _own_upload, build_reply_context_sources
from api.main import app, current_user
from security.auth import CurrentUser
from storage import reset_db, save_conversation
from storage.context_sources import (
    list_whatsapp_chunks,
    list_whatsapp_imports,
    list_whatsapp_messages,
    list_whatsapp_style_profiles,
    save_context_source,
    save_whatsapp_import_bundle,
)

USER_ID = "own-upload-user"


def _upload(style_kind: str) -> dict:
    source = save_context_source(
        {"user_id": USER_ID, "conversation_id": "chat", "source_type": "whatsapp_chat" if style_kind == "user_style" else "friend_style", "title": "Riya", "content": "style summary", "metadata": {"style_kind": style_kind}}
    )
    save_whatsapp_import_bundle(
        {
            "conversation_id": "chat",
            "context_source_id": source["id"],
            "style_kind": style_kind,
            "title": "Riya",
            "selected_sender": "Me",
            "chunks": [{"chunk_index": 0, "start_message_index": 0, "end_message_index": 1, "content": "Riya: remember our goa trip plan", "terms": ["goa", "trip", "plan"], "embedding": [], "metadata": {}}],
        },
        USER_ID,
    )
    return source


class OwnUploadContextTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": "chat", "status": "active", "messages": []}, USER_ID)
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_own_upload_brings_no_old_chunks_into_replies(self) -> None:
        _upload("user_style")
        sources = build_reply_context_sources("chat", None, "remember the goa trip plan from my whatsapp chat?", USER_ID)
        self.assertFalse(any(source["source_type"] == "whatsapp_structured_context" for source in sources))

    def test_only_a_users_own_chat_counts_as_own(self) -> None:
        self.assertTrue(_own_upload({"source_type": "whatsapp_chat", "metadata": {"style_kind": "user_style"}}))
        self.assertFalse(_own_upload({"source_type": "friend_style", "metadata": {"style_kind": "friend_style"}}))


EXPORT = "\n".join(
    f"1{day}/10/2026, 9:{minute:02d} pm - {'Me' if minute % 2 else 'Riya'}: message {day}-{minute} about the goa trip plan"
    for day in range(1, 4)
    for minute in range(10, 30)
)


class OwnUploadRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email="o@example.com", display_name="Me")

        app.dependency_overrides[current_user] = signed_in_user
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false", "AGENT_PIPELINE_VERSION": "v3", "DATA_POINT_EXTRACTOR": "rules", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def test_own_upload_keeps_no_second_copy_but_keeps_style_numbers(self) -> None:
        conversation_id = self.client.post("/api/agent/conversations").json()["id"]
        with patch("agent.cognition.background.uploads.request_flush_now"):
            response = self.client.post(
                f"/api/agent/conversations/{conversation_id}/whatsapp-import",
                json={"title": "Riya", "content": EXPORT, "user_sender": "Me", "style_kind": "user_style"},
            )
        self.assertEqual(response.status_code, 201)
        [upload] = list_whatsapp_imports(user_id=USER_ID)
        self.assertEqual(list_whatsapp_messages(upload["id"], USER_ID), [])
        self.assertEqual(list_whatsapp_chunks(upload["id"], USER_ID), [])
        self.assertTrue(list_whatsapp_style_profiles(upload["id"], USER_ID))


if __name__ == "__main__":
    unittest.main()
