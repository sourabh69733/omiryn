"""Before deleting a chat the user sees what goes with it; old orphan vibe proof cleans itself up."""

import unittest

from fastapi.testclient import TestClient

from storage import create_agent_memory, get_vibe_card, reset_db, save_conversation, update_vibe_card

USER = "impact-user"
CHAT, OTHER = "impact-chat", "other-chat"


def memory(key: str, chats: list[str]) -> None:
    create_agent_memory(
        {
            "user_id": USER,
            "kind": "semantic",
            "purposes": ["profile"],
            "key": key,
            "value": key,
            "allowed_uses": ["reply_context"],
            "confidence": 0.9,
            "importance": 0.5,
            "evidence": [
                {"conversation_id": chat, "message_index": 0, "exact_quote": "hi there", "observed_at": "2026-10-01T10:00:00Z"}
                for chat in chats
            ],
        }
    )


def proof(chat: str) -> dict:
    return {"conversation_id": chat, "message_index": 0, "sent_at": "2026-10-01T10:00:00+00:00"}


class DeletionImpactTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        for chat in (CHAT, OTHER):
            save_conversation({"id": chat, "status": "active", "messages": [{"role": "user", "content": "hi there"}]}, USER)
        from api.main import app
        from security.auth import CurrentUser, require_user

        app.dependency_overrides[require_user] = lambda: CurrentUser(id=USER, email="impact@example.com")
        self.app = app
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    def test_impact_lists_forgotten_memories_and_vibe_lines(self) -> None:
        memory("only_here", [CHAT])
        memory("also_elsewhere", [CHAT, OTHER])
        update_vibe_card(
            USER,
            {
                "humor": {"text": "Likes dry jokes.", "evidence": [proof(CHAT)]},
                "interests": {"text": "Loves F1.", "evidence": [proof(CHAT), proof(OTHER)]},
                "values": {"text": "Values honesty.", "evidence": [proof(OTHER)]},
            },
        )

        body = self.client.get(f"/api/agent/conversations/{CHAT}/deletion-impact").json()

        self.assertEqual(body["memories_forgotten"], 1)
        self.assertEqual(body["vibe_removed"], ["humor"])
        self.assertEqual(body["vibe_weakened"], ["interests"])
        self.assertEqual(self.client.get("/api/agent/conversations/nope/deletion-impact").status_code, 404)

    def test_vibe_page_drops_proof_from_chats_that_no_longer_exist(self) -> None:
        update_vibe_card(
            USER,
            {
                "humor": {"text": "Likes dry jokes.", "evidence": [proof("deleted-long-ago")]},
                "interests": {"text": "Loves F1.", "evidence": [proof("deleted-long-ago"), proof(OTHER)]},
            },
        )

        areas = {area["id"]: area for area in self.client.get("/api/me/vibe").json()["areas"]}

        self.assertIsNone(areas["humor"]["text"])
        self.assertEqual(areas["interests"]["evidence_count"], 1)
        self.assertNotIn("humor", get_vibe_card(USER)["areas"])


if __name__ == "__main__":
    unittest.main()
