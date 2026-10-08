"""Clearing Omi deletes every chat and everything Omi learned, but keeps the account."""

import unittest

from fastapi.testclient import TestClient

from api.main import app
from security.auth import CurrentUser, require_user
from storage import (
    add_open_questions,
    create_agent_memory,
    get_user_card,
    get_vibe_card,
    list_agent_memories,
    list_conversations,
    list_open_questions,
    reset_db,
    save_conversation,
    set_user_card,
    set_user_timezone,
    get_user_timezone,
    update_vibe_card,
)

USER_ID = "clear-omi-user"
OTHER = "someone-else"


def _seed(user_id: str) -> None:
    save_conversation({"id": f"{user_id}-chat", "status": "active", "messages": [{"role": "user", "content": "I love chai."}]}, user_id)
    create_agent_memory(
        {
            "user_id": user_id,
            "kind": "semantic",
            "purposes": ["personalization"],
            "key": "drink",
            "value": "chai",
            "evidence": [{"conversation_id": f"{user_id}-chat", "message_index": 0, "exact_quote": "I love chai.", "observed_at": "2026-10-01T10:00:00+00:00"}],
        }
    )
    set_user_card(user_id, "Loves chai.")
    update_vibe_card(user_id, {"interests": {"text": "Loves chai.", "evidence": [{"conversation_id": f"{user_id}-chat", "message_index": 0, "sent_at": "2026-10-01T10:00:00+00:00"}]}})
    add_open_questions(user_id, f"{user_id}-chat", [{"id": f"{user_id}-q", "text": "Chai or coffee?", "message_index": 0}])


class ClearOmiTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        _seed(USER_ID)
        _seed(OTHER)
        set_user_timezone(USER_ID, "Asia/Kolkata")
        app.dependency_overrides[require_user] = lambda: CurrentUser(id=USER_ID, email="c@example.com", display_name="C")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_it_needs_the_typed_word(self) -> None:
        self.assertEqual(self.client.post("/api/me/omi/clear", json={"confirm": "yes"}).status_code, 400)
        self.assertEqual(len(list_agent_memories(USER_ID)), 1)

    def test_everything_omi_has_goes_and_the_account_stays(self) -> None:
        body = self.client.post("/api/me/omi/clear", json={"confirm": "Clear"}).json()

        self.assertEqual((body["conversations"], body["memories"]), (1, 1))
        self.assertEqual(list_conversations(USER_ID), [])
        self.assertEqual(list_agent_memories(USER_ID), [])
        self.assertIsNone(get_user_card(USER_ID))
        self.assertEqual(get_vibe_card(USER_ID)["areas"], {})
        self.assertEqual(list_open_questions(USER_ID), [])
        self.assertEqual(get_user_timezone(USER_ID), "Asia/Kolkata")
        self.assertEqual(len(list_agent_memories(OTHER)), 1)


if __name__ == "__main__":
    unittest.main()
