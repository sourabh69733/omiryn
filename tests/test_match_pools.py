"""Match pools: an operator creates one, members join with its code, the operator sees who is
ready (non-private lines only), proposes pairs and records what came of them."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.shared.vibe import BASIC_AREA_IDS, DEEPER_AREA_IDS
from api.main import app, current_user
from security.auth import CurrentUser
from agent.matching.pool import operator_check
from storage import (
    create_agent_memory, create_match_pool, get_match_pair, join_match_pool, reset_db, save_conversation, save_match_pair, save_user_profile,
    set_match_pair_plan, set_match_pair_status, update_match_pair_plan, update_vibe_card,
)
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

        writer = AsyncMock(return_value={"fit": "yes", "reasons": [{"source": "area:humor", "text": "Aman and Bela both have the same humor line about them."}]})
        with patch("agent.providers.judge_match", writer):
            pair = self.client.post(f"/api/admin/pools/{pool['id']}/pairs", json={"user_a": "ua", "user_b": "ub"}).json()
        self.assertEqual((pair["status"], pair["check"]["fit"]), ("proposed", "yes"))
        self.assertEqual(self.client.post(f"/api/admin/pools/{pool['id']}/pairs", json={"user_a": "ua", "user_b": "zz"}).status_code, 400)

        view = self.client.get(f"/api/admin/pools/{pool['id']}").json()
        self.assertEqual(view["suggestions"], [])  # already paired
        self.assertEqual(len(view["pairs"]), 1)

        self.assertEqual(self.client.patch(f"/api/admin/pairs/{pair['id']}", json={"status": "met"}).json()["status"], "met")
        self.assertEqual(self.client.patch(f"/api/admin/pairs/{pair['id']}", json={"status": "vanished"}).status_code, 400)
        # Bela has heard nothing from Omi about this pair, so it is not hers to see at any status.
        self._as("ub")
        self.assertEqual(self.client.get("/api/me/pools").json()["pairs"], [])
        for status in ("candidate", "proposed", "asked"):
            set_match_pair_status(pair["id"], status)
            self.assertEqual(self.client.get("/api/me/pools").json()["pairs"], [], status)
        # Once Omi told her, she sees the pair and its status, never the reasons.
        update_match_pair_plan(pair["id"], lambda plan: {**plan, "told": {"ub": {"at": "2026-11-20T10:00:00+00:00", "sent": True}}}, status="met")
        self.assertEqual(self.client.get("/api/me/pools").json()["pairs"][0]["status"], "met")
        self.assertNotIn("check", self.client.get("/api/me/pools").json()["pairs"][0])
        self._as("ua")
        self.assertEqual(self.client.get("/api/me/pools").json()["pairs"], [])  # Aman was not told
        self._as("ub")

        self.assertTrue(self.client.delete(f"/api/me/pools/{pool['id']}").json()["left"])
        self.assertEqual(self.client.get("/api/admin/pools").json()["pools"][0]["member_count"], 2)

        deleted = delete_user_private_data("ua")["deleted"]
        self.assertEqual((deleted["match_pool_members"], deleted["match_pairs"]), (1, 1))

    def test_the_operator_never_gets_memory_texts_or_answer_notes(self) -> None:
        pool = create_match_pool("Baner block A")
        for user_id, name in (("ua", "Aman Verma"), ("ub", "Bela Rao")):
            save_user_profile(user_id, "male", "female", display_name=name)
            join_match_pool(user_id, pool["join_code"])
        check = {
            "version": 2, "fit": "yes", "score": 61, "comparable": ["humor", "interests", "values"],
            "reasons": [{"source": "area:humor", "area": "humor", "text": "Aman and Bela both like dry humour."}],
            "difference": {"source": "area:social_energy", "area": "social_energy", "text": "Aman plans, Bela decides late."},
            "icebreaker": "Ask about the worst chai in Baner.",
            "why_not": "Bela's belief line would grate on Aman.",
            "clash": {"source": "area:deal_breakers", "note": "Aman cannot stand people who cancel late."},
            "meet_fit": {"level": "easy", "line": "both free weekday evenings"},
            "chemistry": "Bela carries the first ten minutes.",
            "touchpoints": [{"memory_a": "m1", "memory_b": "m2", "a": "Aman's sister moved to Canada last spring.", "b": "Bela misses her brother in Toronto.", "similarity": 0.71, "reason_ok": False}],
            "style_lines": ["both write mostly Hinglish"],
        }
        plan = {
            "asked_at": "2026-11-20T10:00:00+00:00", "answer_by": "2026-11-22T10:00:00+00:00", "expired_count": 0, "set_by": "op",
            "told": {"ua": {"at": "2026-11-20T10:01:00+00:00", "sent": True}},
            "answers": {"ua": {"answer": "accept", "note": "said her week is rough but yes", "at": "2026-11-20T11:00:00+00:00"}},
            "outcomes": [{"user_id": "ua", "outcome": "met", "note": "they talked about her father", "at": "2026-11-25T10:00:00+00:00"}],
        }
        pair = save_match_pair(pool["id"], "ua", "ub", check, created_by="op")
        set_match_pair_plan(pair["id"], plan, status="asked")

        view = self.client.get(f"/api/admin/pools/{pool['id']}").json()
        shown = view["pairs"][0]
        for private in ("Canada", "Toronto", "cancel late", "belief line", "Hinglish", "week is rough", "her father"):
            self.assertNotIn(private, str(view), private)
        # What both people are told anyway, the lines the design gives the operator, and counts for the rest.
        self.assertEqual((shown["check"]["fit"], shown["check"]["score"], shown["check"]["clash"]), ("yes", 61, True))
        self.assertEqual(shown["check"]["reasons"][0]["text"], "Aman and Bela both like dry humour.")
        self.assertEqual(shown["check"]["chemistry"], "Bela carries the first ten minutes.")
        self.assertEqual((shown["check"]["touchpoints"], shown["check"]["style_lines"], shown["check"]["why_not"]), (1, 1, None))
        self.assertEqual(shown["plan"]["answers"], {"ua": {"answer": "accept", "at": "2026-11-20T11:00:00+00:00"}})
        self.assertEqual(shown["plan"]["told"], {"ua": {"at": "2026-11-20T10:01:00+00:00", "sent": True}})
        self.assertEqual(shown["plan"]["outcomes"], [{"user_id": "ua", "outcome": "met", "at": "2026-11-25T10:00:00+00:00"}])
        # Every other admin answer that carries a pair is cut the same way.
        patched = self.client.patch(f"/api/admin/pairs/{pair['id']}", json={"status": "met"}).json()
        self.assertEqual(patched["status"], "met")
        self.assertNotIn("Canada", str(patched))
        self.assertNotIn("week is rough", str(patched))
        # Too little to compare is a line code wrote, so the operator may read it.
        self.assertEqual(operator_check({"fit": "unknown", "why_not": "only 2 areas to compare; needs 3"})["why_not"], "only 2 areas to compare; needs 3")
        # Storage keeps the whole check: the judge's evidence is not lost, only not sent.
        self.assertEqual(len(get_match_pair(pair["id"])["check"]["touchpoints"]), 1)


if __name__ == "__main__":
    unittest.main()
