"""The chat between two introduced people: only the two reach it, it opens with the introduction,
unread counts and paging hold, a block or a report closes it for both and keeps the two apart for
good, the other person is told only that it is off, and deleting an account removes the chat."""

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.context_engine.sources.match_hosting import match_hosting_sources
from agent.jobs.worker import JobWorker
from agent.matching.asking import MATCH_NOT_THIS_WEEK_JOB, ask_pair
from agent.matching.hosting import run_match_intro_job
from agent.matching.pair_chat import MATCH_CLOSED_JOB, chat_state, close_pair
from agent.matching.pick import eligible_pairs
from agent.matching.pool import pool_view, propose_pair
from api.main import app, current_user
from security.auth import CurrentUser
from storage import (
    add_match_message,
    blocked_match_pairs,
    create_match_pool,
    delete_user_private_data,
    get_agent_job,
    get_match_pair,
    join_match_pool,
    list_match_messages,
    list_match_reports,
    match_chat_counts,
    reset_db,
    save_conversation,
    save_match_pair,
    save_user_profile,
    set_match_pair_plan,
)

CHECK = {
    "fit": "yes",
    "reasons": [{"source": "area:humor", "area": "humor", "text": "Aman and Bela both like dry humour."}],
    "difference": None,
    "icebreaker": "Ask about the worst chai in Baner.",
    "score": 60,
}
DAY = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)  # 14:30 in India
TOLD = {"told": {"ua": {"at": DAY.isoformat(), "sent": True}, "ub": {"at": DAY.isoformat(), "sent": True}}}


def _user(user_id: str, name: str) -> None:
    save_user_profile(user_id, "male", "female", display_name=name)
    save_conversation({"id": f"{user_id}-web", "status": "active", "messages": [{"role": "user", "content": "hi", "created_at": "2026-10-20T10:00:00+00:00"}]}, user_id)


class _As:
    """A test client signed in as one user."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    def __enter__(self) -> TestClient:
        app.dependency_overrides[current_user] = lambda: CurrentUser(id=self.user_id, email=f"{self.user_id}@x.com", display_name=self.user_id)
        return TestClient(app)

    def __exit__(self, *exc) -> None:
        app.dependency_overrides.pop(current_user, None)


class PairChatTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PROVIDER": "mock", "AUTH_REQUIRED": "false", "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "true"})
        self.env.start()
        for user_id, name in (("ua", "Aman Verma"), ("ub", "Bela Rao"), ("uc", "Chirag Shah")):
            _user(user_id, name)
        self.pool = create_match_pool("Baner block A")
        for user_id in ("ua", "ub", "uc"):
            join_match_pool(user_id, self.pool["join_code"])
        self.pair = save_match_pair(self.pool["id"], "ua", "ub", CHECK, created_by="op")
        self.publish = patch("api.routes.match_chat.realtime_hub.publish", new=AsyncMock(return_value=0))
        self.published = self.publish.start()

    def tearDown(self) -> None:
        self.publish.stop()
        self.env.stop()

    def _introduce(self) -> str:
        set_match_pair_plan(self.pair["id"], dict(TOLD), status="introduced", introduced_at=DAY)
        return self.pair["id"]

    def test_only_the_two_write_and_read_after_the_introduction(self) -> None:
        pair_id = self.pair["id"]
        with _As("ua") as client:
            # Proposed, not introduced: there is no chat yet.
            self.assertEqual(client.get(f"/api/me/matches/{pair_id}/messages").status_code, 404)
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/messages", json={"text": "hi"}).status_code, 404)
        self._introduce()
        with _As("ua") as client:
            sent = client.post(f"/api/me/matches/{pair_id}/messages", json={"text": "  Hi Bela, chai on Sunday?  ", "client_id": "c1"})
            self.assertEqual(sent.status_code, 201)
            message = sent.json()["message"]
            self.assertEqual((message["mine"], message["text"], message["client_id"]), (True, "Hi Bela, chai on Sunday?", "c1"))
            self.assertNotIn("sender_id", message)
            # A retried send with the same client id is saved once.
            again = client.post(f"/api/me/matches/{pair_id}/messages", json={"text": "Hi Bela, chai on Sunday?", "client_id": "c1"}).json()["message"]
            self.assertEqual(again["id"], message["id"])
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/messages", json={"text": "   "}).status_code, 400)
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/messages", json={"text": "x" * 2001}).status_code, 422)
            card = client.get("/api/me/matches").json()["matches"][0]
            self.assertEqual(card["chat"], {"open": True, "messages": 1, "unread": 0, "last_at": card["chat"]["last_at"]})
        # Both people are told a message exists, by id only: the text never rides on the event.
        events = [call.args[0] for call in self.published.await_args_list if call.args[0].type == "match.message"]
        self.assertEqual({event.scope_id for event in events}, {"ua", "ub"})
        self.assertEqual(events[0].payload, {"pair_id": pair_id, "message_id": message["id"]})
        with _As("ub") as client:
            page = client.get(f"/api/me/matches/{pair_id}/messages").json()
            self.assertEqual([(m["mine"], m["text"], m["client_id"]) for m in page["messages"]], [(False, "Hi Bela, chai on Sunday?", None)])
            self.assertEqual((page["chat"]["unread"], page["has_more"]), (1, False))
            self.assertEqual(client.get("/api/me/matches").json()["matches"][0]["chat"]["unread"], 1)
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/read").json()["chat"]["unread"], 0)
            client.post(f"/api/me/matches/{pair_id}/messages", json={"text": "Sunday works"})
        with _As("uc") as client:  # in the pool, not in the pair
            self.assertEqual(client.get(f"/api/me/matches/{pair_id}/messages").status_code, 404)
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/messages", json={"text": "hello"}).status_code, 404)
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/block").status_code, 404)
        counts = match_chat_counts([pair_id])[pair_id]
        self.assertEqual((counts["messages"], counts["by_user"]), (2, {"ua": 1, "ub": 1}))
        # The operator sees how much they wrote, never what.
        view_pair = next(p for p in pool_view(self.pool["id"])["pairs"] if p["id"] == pair_id)
        self.assertEqual(view_pair["chat"]["messages"], 2)
        self.assertNotIn("Sunday", str(view_pair["chat"]))

    def test_paging_goes_back_and_catches_up(self) -> None:
        pair_id = self._introduce()
        ids = [add_match_message(pair_id, "ua" if i % 2 else "ub", f"m{i}")["id"] for i in range(7)]
        with _As("ua") as client:
            newest = client.get(f"/api/me/matches/{pair_id}/messages?limit=3").json()
            self.assertEqual(([m["text"] for m in newest["messages"]], newest["has_more"]), (["m4", "m5", "m6"], True))
            older = client.get(f"/api/me/matches/{pair_id}/messages?limit=3&before={newest['messages'][0]['id']}").json()
            self.assertEqual([m["text"] for m in older["messages"]], ["m1", "m2", "m3"])
            oldest = client.get(f"/api/me/matches/{pair_id}/messages?limit=3&before={older['messages'][0]['id']}").json()
            self.assertEqual(([m["text"] for m in oldest["messages"]], oldest["has_more"]), (["m0"], False))
            caught_up = client.get(f"/api/me/matches/{pair_id}/messages?after={ids[4]}").json()
            self.assertEqual([m["text"] for m in caught_up["messages"]], ["m5", "m6"])
            # Reading part of the way leaves the rest unread; the mark never moves back.
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/read", json={"upto": ids[2]}).json()["chat"]["unread"], 2)
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/read", json={"upto": ids[0]}).json()["last_read_id"], ids[2])

    def test_a_script_is_slowed_down(self) -> None:
        pair_id = self._introduce()
        with _As("ua") as client, patch("api.routes.match_chat.MESSAGES_PER_MINUTE", 2):
            codes = [client.post(f"/api/me/matches/{pair_id}/messages", json={"text": f"m{i}"}).status_code for i in range(3)]
        self.assertEqual(codes, [201, 201, 429])

    async def test_a_block_closes_it_for_both_and_keeps_them_apart(self) -> None:
        pair_id = self._introduce()
        add_match_message(pair_id, "ub", "hey")
        with _As("ua") as client:
            blocked = client.post(f"/api/me/matches/{pair_id}/block").json()
            self.assertEqual((blocked["status"], blocked["match"]["status"], blocked["match"]["chat"]["open"]), ("blocked", "blocked", False))
            # The history stays readable; nothing new goes in.
            self.assertEqual(len(client.get(f"/api/me/matches/{pair_id}/messages").json()["messages"]), 1)
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/messages", json={"text": "one more"}).status_code, 409)
        self.assertEqual(get_match_pair(pair_id)["status"], "declined")
        with _As("ub") as client:
            card = client.get("/api/me/matches").json()["matches"][0]
            self.assertEqual((card["status"], card["chat"]["open"]), ("declined", False))  # never told it was a block
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/messages", json={"text": "hello?"}).status_code, 409)
        # Bela hears only that it is off; Aman, who ended it, hears nothing.
        self.assertIsNotNone(get_agent_job(f"{MATCH_CLOSED_JOB}:ub:{pair_id}:closed"))
        self.assertIsNone(get_agent_job(f"{MATCH_CLOSED_JOB}:ua:{pair_id}:closed"))
        seen: list[str] = []

        async def generate(conversation, user_id, *, instructions, **kwargs):
            seen.append(instructions)
            return "That introduction isn't going ahead. I'll keep an eye out."

        with patch("agent.proactive.service.generate_initiative_text", generate), patch("agent.matching.hosting.utc_now", return_value=DAY):
            self.assertEqual(await JobWorker().run_once(), 1)
        self.assertIn("The introduction to Aman is off", seen[0])
        self.assertNotIn("block", seen[0].lower())
        # Omi's standing context does not tell Bela she said no, and does not say why.
        self.assertIn("not by this user's choice", match_hosting_sources("ub")[0]["content"])
        self.assertIn("the user said no to it", match_hosting_sources("ua")[0]["content"])
        # Never offered to each other again: not by the pick in any pool, not by hand.
        self.assertEqual(blocked_match_pairs(["ua"]), {frozenset(("ua", "ub"))})
        self.assertEqual([(a, b) for a, b, _ in eligible_pairs(["ua", "ub", "uc"], [], blocked_match_pairs(["ua", "ub", "uc"]))], [("ua", "uc"), ("ub", "uc")])
        with self.assertRaises(ValueError):
            await propose_pair(self.pool["id"], "ub", "ua")
        self.assertFalse(any({s["user_a"], s["user_b"]} == {"ua", "ub"} for s in pool_view(self.pool["id"])["suggestions"]))

    def test_a_report_goes_to_the_team_and_can_leave_the_block_off(self) -> None:
        pair_id = self._introduce()
        with _As("ub") as client:
            self.assertEqual(client.post(f"/api/me/matches/{pair_id}/report", json={"reason": "rude"}).status_code, 400)
            reported = client.post(f"/api/me/matches/{pair_id}/report", json={"reason": "spam", "note": "kept  selling a course", "block": False}).json()
            self.assertEqual((reported["status"], reported["match"]["status"]), ("declined", "declined"))
        self.assertEqual(blocked_match_pairs(), set())
        report = list_match_reports()[0]
        self.assertEqual((report["reporter_id"], report["reported_id"], report["reason"], report["note"]), ("ub", "ua", "spam", "kept selling a course"))
        with patch("admin.auth.production_runtime_enabled", return_value=False):
            listed = TestClient(app).get("/api/admin/match-reports")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["reports"][0]["id"], report["id"])
        # A second report on the closed pair is still recorded, and may add the block.
        self.assertEqual(close_pair(pair_id, "ub", block=True, reason="other")["status"], "blocked")
        self.assertEqual(len(list_match_reports()), 2)

    async def test_a_report_before_the_introduction_is_a_pass(self) -> None:
        with patch("agent.matching.asking.utc_now", return_value=DAY):
            await ask_pair(self.pair["id"], created_by="op")
        set_match_pair_plan(self.pair["id"], {**(get_match_pair(self.pair["id"])["plan"] or {}), **TOLD})
        self.assertEqual(close_pair(self.pair["id"], "ua", block=True, reason="uncomfortable")["status"], "blocked")
        self.assertEqual(get_match_pair(self.pair["id"])["status"], "declined")
        self.assertIsNotNone(get_agent_job(f"{MATCH_NOT_THIS_WEEK_JOB}:ub:{self.pair['id']}:ntw"))
        self.assertFalse(chat_state(get_match_pair(self.pair["id"]), "ub")["open"])

    async def test_omi_points_to_the_chat_only_when_the_app_has_it(self) -> None:
        pair_id = self._introduce()
        seen: list[str] = []

        async def generate(conversation, user_id, *, instructions, **kwargs):
            seen.append(instructions)
            return "Meet Bela."

        job = {"user_id": "ua", "payload": {"pair_id": pair_id}}
        with patch("agent.proactive.service.generate_initiative_text", generate):
            await run_match_intro_job(job)
            with patch.dict(os.environ, {"MATCH_CHAT_IN_APP": "true"}):
                await run_match_intro_job(job)
                self.assertIn("You cannot see that chat", match_hosting_sources("ua")[-1]["content"])
        self.assertNotIn("under Matches, there is a chat", seen[0])
        self.assertIn("under Matches, there is a chat with Bela", seen[1])
        self.assertNotIn("You cannot see that chat", match_hosting_sources("ua")[-1]["content"])

    def test_deleting_an_account_removes_the_chat(self) -> None:
        pair_id = self._introduce()
        add_match_message(pair_id, "ua", "hi")
        add_match_message(pair_id, "ub", "hello")
        close_pair(pair_id, "ub", block=True, reason="other", note="x")
        deleted = delete_user_private_data("ua")["deleted"]
        self.assertEqual((deleted["match_messages"], deleted["match_blocks"], deleted["match_reports"]), (2, 1, 1))
        self.assertEqual(list_match_messages(pair_id), [])
        self.assertEqual(list_match_reports(), [])


if __name__ == "__main__":
    unittest.main()
