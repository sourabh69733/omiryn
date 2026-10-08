"""Deleting chosen messages removes their text and what Omi learned only from them."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.providers.shared.messages import _provider_messages
from api.main import app
from security.auth import CurrentUser, require_user
from storage import (
    add_open_questions,
    add_self_notes,
    create_agent_memory,
    get_conversation,
    get_vibe_card,
    list_active_self_notes,
    list_agent_memories,
    list_open_questions,
    reset_db,
    save_conversation,
    update_vibe_card,
)

USER_ID = "delete-messages-user"
CHAT = "delete-messages-chat"
MESSAGES = [
    {"role": "user", "content": "I live in Pune.", "created_at": "2026-10-01T10:00:00+00:00"},
    {"role": "assistant", "content": "Pune! I like that the city has hills nearby.", "created_at": "2026-10-01T10:00:05+00:00"},
    {"role": "user", "content": "I love dark humor.", "created_at": "2026-10-01T10:01:00+00:00"},
    {"role": "assistant", "content": "Same, the darker the better.", "created_at": "2026-10-01T10:01:05+00:00"},
    {"role": "user", "content": "Yeah, Pune is home now.", "created_at": "2026-10-02T10:00:00+00:00"},
]


def _memory(key: str, statement: str, indexes: list[int]) -> str:
    return create_agent_memory(
        {
            "user_id": USER_ID,
            "kind": "semantic",
            "purposes": ["personalization"],
            "key": key,
            "value": statement,
            "statement": statement,
            "confidence": 0.9,
            "importance": 0.6,
            "evidence": [
                {"conversation_id": CHAT, "message_index": index, "exact_quote": MESSAGES[index]["content"], "observed_at": MESSAGES[index]["created_at"]}
                for index in indexes
            ],
        }
    )["id"]


class MessageDeletionTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CHAT, "status": "active", "messages": MESSAGES}, USER_ID)
        self.home = _memory("home", "Lives in Pune.", [0, 4])
        self.humor = _memory("humor", "Loves dark humor.", [2])
        update_vibe_card(
            USER_ID,
            {"humor": {"text": "Loves dark humor.", "evidence": [{"conversation_id": CHAT, "message_index": 2, "sent_at": MESSAGES[2]["created_at"]}]}},
        )
        add_self_notes(USER_ID, CHAT, [{"id": "note", "kind": "opinion", "text": "Likes dark humor too.", "message_index": 3}])
        add_open_questions(USER_ID, CHAT, [{"id": "q", "text": "Still in Pune?", "message_index": 4}])

        app.dependency_overrides[require_user] = lambda: CurrentUser(id=USER_ID, email="d@example.com", display_name="D")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _post(self, action: str, indexes: list[int]):
        with patch("api.routes.conversations.request_flush_now") as flush:
            response = self.client.post(f"/api/agent/conversations/{CHAT}/messages/{action}", json={"message_indexes": indexes})
        return response, flush

    def test_the_dialog_shows_what_goes_before_anything_changes(self) -> None:
        response, _ = self._post("deletion-impact", [2, 3])

        self.assertEqual(response.json(), {"message_count": 2, "memories_forgotten": 1, "vibe_removed": ["humor"], "vibe_weakened": []})
        self.assertEqual(get_conversation(CHAT, USER_ID)["messages"][2]["content"], "I love dark humor.")

    def test_deleting_blanks_the_text_and_forgets_what_came_only_from_it(self) -> None:
        response, flush = self._post("delete", [2, 3, 4])

        self.assertEqual(response.status_code, 200)
        messages = get_conversation(CHAT, USER_ID)["messages"]
        self.assertEqual(len(messages), len(MESSAGES))
        self.assertEqual([(m["content"], bool(m.get("deleted"))) for m in messages[2:]], [("", True)] * 3)
        memories = {memory["id"]: memory for memory in list_agent_memories(USER_ID)}
        self.assertNotIn(self.humor, memories)
        self.assertEqual([item["message_index"] for item in memories[self.home]["evidence"]], [0])
        self.assertEqual(get_vibe_card(USER_ID)["areas"], {})
        self.assertEqual(list_active_self_notes(USER_ID), [])
        self.assertEqual(list_open_questions(USER_ID), [])
        flush.assert_called_once()

    def test_the_model_never_sees_a_deleted_message(self) -> None:
        self._post("delete", [2])

        sent = _provider_messages(get_conversation(CHAT, USER_ID)["messages"])
        self.assertNotIn("dark humor", " ".join(message["content"] for message in sent))
        # Omi's replies on either side of it now touch and are sent as one turn.
        self.assertEqual([message["role"] for message in sent], ["user", "assistant", "user"])

    def test_bad_selections_are_refused(self) -> None:
        self.assertEqual(self._post("delete", [99])[0].status_code, 400)
        self.assertEqual(self._post("delete", [])[0].status_code, 422)


if __name__ == "__main__":
    unittest.main()
