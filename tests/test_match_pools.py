"""Match pools: an operator creates one, members join with its code, the operator sees who is
ready (non-private lines only), proposes pairs and records what came of them."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.shared.vibe import BASIC_AREA_IDS, DEEPER_AREA_IDS
from api.main import app, current_user
from security.auth import CurrentUser
from storage import create_agent_memory, reset_db, save_conversation, save_user_profile, update_vibe_card
from storage.user_deletion import delete_user_private_data

from test_matching import line, ready_areas


def _ready_user(user_id: str, name: str) -> None:
    save_user_profile(user_id, "male", "female", display_name=name)
    update_vibe_card(user_id, ready_areas(values=line("Private belief line that must never show.")))
    save_conversation({"id": f"{user_id}-chat", "status": "active", "messages": [{"role": "user", "content": "I live in Baner and I am free most evenings"}]}, user_id)
    for key, statement in (("home.area", "Lives in Baner, Pune."), ("free.time", "Free most weekday evenings and on Sundays.")):
        create_agent_memory({
            "user_id": user_id, "kind": "semantic", "purposes": ["profile"], "key": key, "value": statement, "statement": statement,
            "confidence": 0.9, "importance": 0.6,
            "evidence": [{"conversation_id": f"{user_id}-chat", "message_index": 0, "exact_quote": "I live in Baner", "observed_at": "2026-10-01T10:00:00+00:00"}],
        })


class MatchPoolTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false", "AGENT_PROVIDER": "mock", "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "true"})
        self.env.start()
        app.dependency_overrides.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.env.stop()

    def _as(self, user_id: str) -> None:
        async def signed_in() -> CurrentUser:
            return CurrentUser(id=user_id, email=f"{user_id}@example.com", display_name=user_id)
        app.dependency_overrides[current_user] = signed_in

    def test_the_whole_operator_flow(self) -> None:
        pool = self.client.post("/api/admin/pools", json={"name": "Baner block A", "match_weekday": 6}).json()
        self.assertEqual(len(pool["join_code"]), 6)

        _ready_user("ua", "Aman Verma")
        _ready_user("ub", "Bela Rao")
        save_user_profile("uc", "male", "female", display_name="Chirag")
        for user_id in ("ua", "ub", "uc"):
            self._as(user_id)
            self.assertEqual(self.client.post("/api/me/pools/join", json={"code": pool["join_code"]}).status_code, 200)
        self.assertEqual(self.client.post("/api/me/pools/join", json={"code": "nope99"}).status_code, 404)
        mine = self.client.get("/api/me/pools").json()
        self.assertEqual([p["name"] for p in mine["pools"]], ["Baner block A"])
        self.assertNotIn("join_code", mine["pools"][0])

        view = self.client.get(f"/api/admin/pools/{pool['id']}").json()
        self.assertEqual(len(view["members"]), 3)
        self.assertEqual(view["ready_count"], 2)
        by_id = {m["user_id"]: m for m in view["members"]}
        self.assertTrue(by_id["ua"]["readiness"]["ready"])
        self.assertFalse(by_id["uc"]["readiness"]["ready"])
        self.assertNotIn("values", by_id["ua"]["lines"])  # private areas never shown
        self.assertNotIn("Private belief", str(view))
        self.assertEqual([(s["user_a"], s["user_b"]) for s in view["suggestions"]], [("ua", "ub")])

        writer = AsyncMock(return_value={"fit": "yes", "reasons": [{"area": "humor", "text": "Aman and Bela both like dry humour."}]})
        with patch("agent.providers.write_match_reasons", writer):
            pair = self.client.post(f"/api/admin/pools/{pool['id']}/pairs", json={"user_a": "ua", "user_b": "ub"}).json()
        self.assertEqual((pair["status"], pair["check"]["fit"]), ("proposed", "yes"))
        self.assertEqual(self.client.post(f"/api/admin/pools/{pool['id']}/pairs", json={"user_a": "ua", "user_b": "zz"}).status_code, 400)

        view = self.client.get(f"/api/admin/pools/{pool['id']}").json()
        self.assertEqual(view["suggestions"], [])  # already paired
        self.assertEqual(len(view["pairs"]), 1)

        self.assertEqual(self.client.patch(f"/api/admin/pairs/{pair['id']}", json={"status": "met"}).json()["status"], "met")
        self.assertEqual(self.client.patch(f"/api/admin/pairs/{pair['id']}", json={"status": "vanished"}).status_code, 400)
        self._as("ub")
        self.assertEqual(self.client.get("/api/me/pools").json()["pairs"][0]["status"], "met")
        self.assertNotIn("check", self.client.get("/api/me/pools").json()["pairs"][0])

        self.assertTrue(self.client.delete(f"/api/me/pools/{pool['id']}").json()["left"])
        self.assertEqual(self.client.get("/api/admin/pools").json()["pools"][0]["member_count"], 2)

        deleted = delete_user_private_data("ua")["deleted"]
        self.assertEqual((deleted["match_pool_members"], deleted["match_pairs"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
