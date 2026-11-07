"""Ask both: the operator asks a proposed pair; each person hears about the other in their own chat
and answers through the tool or the app; both yes queues the introduction; a pass closes the pair
and the other hears "not this week"; silence lapses the ask. The match cards show only what the
user may know."""

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.context_engine.sources.match_hosting import match_hosting_sources
from agent.jobs.worker import JobWorker
from agent.matching.asking import MATCH_ASK_EXPIRE_JOB, MATCH_ASK_JOB, MATCH_NOT_THIS_WEEK_JOB, ask_pair, record_answer, run_match_ask_expire_job
from agent.matching.hosting import MATCH_INTRO_JOB
from agent.tools import ToolCall, ToolContext, run_calls, tool_specs
from api.main import app, current_user
from security.auth import CurrentUser
from storage import create_match_pool, get_agent_job, get_conversation, get_match_pair, join_match_pool, reset_db, save_conversation, save_match_pair, save_user_profile

CHECK = {
    "fit": "yes",
    "reasons": [{"source": "area:humor", "area": "humor", "text": "Aman and Bela both like dry humour."}],
    "difference": {"source": "area:social_energy", "area": "social_energy", "text": "Aman plans, Bela decides at 7 pm."},
    "icebreaker": "Ask about the worst chai in Baner.",
    "clash": None,
    "meet_fit": {"level": "easy", "line": "both free weekday evenings"},
    "chemistry": "Bela carries the first ten minutes.",
    "score": 60,
}
DAY = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)  # 14:30 in India


def _user(user_id: str, name: str) -> None:
    save_user_profile(user_id, "male", "female", display_name=name)
    save_conversation({"id": f"{user_id}-web", "status": "active", "messages": [{"role": "user", "content": "hi", "created_at": "2026-10-20T10:00:00+00:00"}]}, user_id)


class AskingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PROVIDER": "mock", "AUTH_REQUIRED": "false"})
        self.env.start()
        _user("ua", "Aman Verma")
        _user("ub", "Bela Rao")
        pool = create_match_pool("Baner block A")
        join_match_pool("ua", pool["join_code"])
        join_match_pool("ub", pool["join_code"])
        self.pair = save_match_pair(pool["id"], "ua", "ub", CHECK, created_by="op")

    def tearDown(self) -> None:
        self.env.stop()

    async def _ask_and_tell_both(self) -> dict:
        pair = await ask_pair(self.pair["id"], created_by="op")
        self.assertEqual(pair["status"], "asked")
        for user_id in ("ua", "ub"):
            self.assertIsNotNone(get_agent_job(f"{MATCH_ASK_JOB}:{user_id}:{pair['id']}:ask"))
        self.assertIsNotNone(get_agent_job(f"{MATCH_ASK_EXPIRE_JOB}:ua:{pair['id']}:expire"))
        seen: list[str] = []

        async def generate(conversation, user_id, *, instructions, **kwargs):
            seen.append(instructions)
            return "There is someone from your building I think you'd get on with.<next_message>Want me to introduce you?"

        with patch("agent.proactive.service.generate_initiative_text", generate), patch("agent.matching.hosting.utc_now", return_value=DAY), patch("agent.matching.asking.utc_now", return_value=DAY):
            self.assertEqual(await JobWorker().run_once(), 2)  # the two asks; the lapse is not due
        self.assertIn("Bela", seen[0])
        self.assertIn("dry humour", seen[0])
        self.assertIn("Aman plans", seen[0])
        self.assertNotIn("worst chai", seen[0])  # the icebreaker waits for the introduction
        self.assertEqual(get_conversation("ua-web", "ua")["messages"][-1]["proactive_kind"], "match_ask")
        return get_match_pair(pair["id"])

    async def test_both_say_yes_through_tool_and_app(self) -> None:
        pair = await self._ask_and_tell_both()
        self.assertTrue(pair["plan"]["told"]["ua"]["sent"] and pair["plan"]["told"]["ub"]["sent"])
        # Omi knows about the open ask and the answer tool is on.
        sources = match_hosting_sources("ua")
        self.assertEqual(sources[0]["title"], "Someone you offered to introduce")
        self.assertIn(f"Bela (pair id {pair['id']})", sources[0]["content"])
        self.assertIn("answer_match", [t["function"]["name"] for t in tool_specs(ToolContext("ua", "ua-web"))])

        results = await run_calls([ToolCall("answer_match", {"pair_id": pair["id"], "answer": "accept", "note": "sure"})], ToolContext("ua", "ua-web"))
        self.assertEqual((results[0].trace["answer"], results[0].trace["status"]), ("accept", "asked"))
        self.assertIn("they said yes; the other person has not answered yet", match_hosting_sources("ua")[0]["content"])
        self.assertNotIn("answer_match", [t["function"]["name"] for t in tool_specs(ToolContext("ua", "ua-web"))])  # answered: off again

        app.dependency_overrides[current_user] = lambda: CurrentUser(id="ub", email="b@x.com", display_name="Bela")
        try:
            client = TestClient(app)
            cards = client.get("/api/me/matches").json()["matches"]
            self.assertEqual((cards[0]["status"], cards[0]["name"]), ("asked", "Aman"))
            self.assertEqual([r["text"] for r in cards[0]["reasons"]], ["Aman and Bela both like dry humour."])
            self.assertNotIn("score", cards[0])
            self.assertNotIn("chemistry", cards[0])
            answered = client.post(f"/api/me/matches/{pair['id']}/answer", json={"answer": "accept"}).json()
            self.assertEqual(answered["status"], "introduced")
            self.assertEqual(answered["match"]["status"], "introduced")
            self.assertEqual(client.post(f"/api/me/matches/{pair['id']}/answer", json={"answer": "pass"}).status_code, 409)
            self.assertEqual(client.post("/api/me/matches/nope/answer", json={"answer": "pass"}).status_code, 404)
        finally:
            app.dependency_overrides.pop(current_user, None)
        after = get_match_pair(pair["id"])
        self.assertEqual(after["status"], "introduced")
        self.assertIsNotNone(after["introduced_at"])
        for user_id in ("ua", "ub"):
            self.assertIsNotNone(get_agent_job(f"{MATCH_INTRO_JOB}:{user_id}:{pair['id']}"))
        # Aman's card now says introduced and waiting Omi's introduction; nothing of Bela's beyond the card.
        app.dependency_overrides[current_user] = lambda: CurrentUser(id="ua", email="a@x.com", display_name="Aman")
        try:
            card = TestClient(app).get("/api/me/matches").json()["matches"][0]
            self.assertEqual((card["status"], card["name"], card["plan"]), ("introduced", "Bela", None))
        finally:
            app.dependency_overrides.pop(current_user, None)

    async def test_a_pass_closes_the_pair_and_the_other_hears_not_this_week(self) -> None:
        pair = await self._ask_and_tell_both()
        result = record_answer(pair["id"], "ub", "pass")
        self.assertEqual(result, {"ok": True, "status": "declined", "both": False})
        self.assertEqual(get_match_pair(pair["id"])["status"], "declined")
        self.assertIsNotNone(get_agent_job(f"{MATCH_NOT_THIS_WEEK_JOB}:ua:{pair['id']}:ntw"))
        self.assertIsNone(get_agent_job(f"{MATCH_NOT_THIS_WEEK_JOB}:ub:{pair['id']}:ntw"))
        seen: list[str] = []

        async def generate(conversation, user_id, *, instructions, **kwargs):
            seen.append(instructions)
            return "Small change: that intro is not happening this week. I'll keep an eye out."

        with patch("agent.proactive.service.generate_initiative_text", generate), patch("agent.matching.hosting.utc_now", return_value=DAY):
            self.assertGreaterEqual(await JobWorker().run_once(), 1)
        self.assertIn("NOT THIS WEEK", seen[0])
        self.assertIn("do not mention Bela's answer", seen[0])
        self.assertEqual(get_conversation("ua-web", "ua")["messages"][-1]["proactive_kind"], "match_not_this_week")
        # Late answers do nothing.
        self.assertEqual(record_answer(pair["id"], "ua", "accept")["error"], "not_open")
        self.assertEqual(record_answer(pair["id"], "zz", "accept")["error"], "unknown_pair")
        self.assertEqual(record_answer(pair["id"], "ua", "maybe")["error"], "bad_answer")

    async def test_silence_lapses_the_ask_and_tells_only_who_said_yes(self) -> None:
        pair = await self._ask_and_tell_both()
        record_answer(pair["id"], "ua", "accept")
        job = {"id": "j", "kind": MATCH_ASK_EXPIRE_JOB, "user_id": "ua", "conversation_id": None, "payload": {"pair_id": pair["id"]}}
        self.assertTrue(await run_match_ask_expire_job(job))
        after = get_match_pair(pair["id"])
        self.assertEqual((after["status"], after["plan"]["expired_count"]), ("expired", 1))
        self.assertIsNotNone(get_agent_job(f"{MATCH_NOT_THIS_WEEK_JOB}:ua:{pair['id']}:ntw"))
        self.assertIsNone(get_agent_job(f"{MATCH_NOT_THIS_WEEK_JOB}:ub:{pair['id']}:ntw"))
        self.assertFalse(await run_match_ask_expire_job(job))  # already lapsed

    def test_operator_endpoint_and_a_pair_that_is_not_proposed(self) -> None:
        with patch.dict(os.environ, {"AUTH_REQUIRED": "false", "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "true"}):
            client = TestClient(app)
            self.assertEqual(client.post(f"/api/admin/pairs/{self.pair['id']}/ask").json()["status"], "asked")
            self.assertEqual(client.post(f"/api/admin/pairs/{self.pair['id']}/ask").status_code, 409)
            self.assertEqual(client.post("/api/admin/pairs/nope/ask").status_code, 404)
            self.assertEqual(client.post(f"/api/admin/pairs/{self.pair['id']}/introduce", json={}).status_code, 409)  # asked, not proposed


if __name__ == "__main__":
    unittest.main()
