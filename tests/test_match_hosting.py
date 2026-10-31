"""Omi as host: the operator introduces a pair, both people hear about it in their own chat with Omi
(WhatsApp when linked), a reminder and two check-ins are queued, nothing goes out once a pair is
closed, and what the user says came of it is recorded through a tool in a normal turn."""

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.jobs.worker import JobWorker
from agent.matching.hosting import (
    MATCH_CHECK_IN_JOB,
    MATCH_INTRO_JOB,
    MATCH_REMINDER_JOB,
    follow_up_times,
    hosting_conversation,
    introduce_pair,
    run_match_check_in_job,
)
from agent.context_engine.sources.match_hosting import match_hosting_sources
from agent.tools import ToolCall, ToolContext, run_calls, tool_specs
from api.main import app
from storage import (
    create_match_pool,
    get_agent_job,
    get_conversation,
    get_match_pair,
    join_match_pool,
    link_channel_chat,
    reset_db,
    save_conversation,
    save_match_pair,
    save_user_profile,
    set_match_pair_status,
)

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
CHECK = {
    "fit": "yes",
    "reasons": [{"area": "humor", "text": "Aman and Bela both like dry humour."}],
    "difference": {"area": "energy", "text": "Aman is up early, Bela is a night owl."},
    "icebreaker": "Ask about the worst chai in Baner.",
}


def _user(user_id: str, name: str, *, channel: str | None = None) -> None:
    save_user_profile(user_id, "male", "female", display_name=name)
    save_conversation(
        {"id": f"{user_id}-web", "status": "active", "messages": [{"role": "user", "content": "hi", "created_at": "2026-10-20T10:00:00+00:00"}]},
        user_id,
    )
    if channel:
        link_channel_chat(user_id, channel, f"{user_id}-phone")
        save_conversation(
            {"id": f"{user_id}-{channel}", "status": "active", "channel": channel, "messages": [{"role": "user", "content": "hey", "created_at": "2026-10-21T10:00:00+00:00"}]},
            user_id,
        )


def _pair() -> dict:
    pool = create_match_pool("Baner block A")
    join_match_pool("ua", pool["join_code"])
    join_match_pool("ub", pool["join_code"])
    return save_match_pair(pool["id"], "ua", "ub", CHECK, created_by="op")


class HostingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PROVIDER": "mock", "WHATSAPP_ENABLED": "true", "WHATSAPP_ACCESS_TOKEN": "t",
                                           "WHATSAPP_PHONE_NUMBER_ID": "1", "WHATSAPP_PHONE_NUMBER": "911", "WHATSAPP_APP_SECRET": "s", "WHATSAPP_VERIFY_TOKEN": "v"})
        self.env.start()
        _user("ua", "Aman Verma", channel="whatsapp")
        _user("ub", "Bela Rao")
        self.pair = _pair()

    def tearDown(self) -> None:
        self.env.stop()

    def test_hosting_chat_prefers_the_linked_channel(self) -> None:
        self.assertEqual(hosting_conversation("ua")["id"], "ua-whatsapp")
        self.assertEqual(hosting_conversation("ub")["id"], "ub-web")

    def test_follow_up_times(self) -> None:
        meet_at = NOW + timedelta(days=5)
        steps = {kind: (at, extra) for kind, at, extra in follow_up_times(NOW, meet_at)}
        self.assertEqual(steps[MATCH_REMINDER_JOB][0], meet_at - timedelta(days=1))
        self.assertEqual(steps[MATCH_CHECK_IN_JOB][0], NOW + timedelta(days=30))  # the last check-in wins the key here
        kinds = [(kind, extra.get("day")) for kind, _, extra in follow_up_times(NOW, meet_at)]
        self.assertEqual(kinds, [(MATCH_REMINDER_JOB, None), (MATCH_CHECK_IN_JOB, 3), (MATCH_CHECK_IN_JOB, 30)])
        # Short notice: the reminder moves to three hours before; no time at all: no reminder, day 3 counts from now.
        soon = [kind for kind, _, _ in follow_up_times(NOW, NOW + timedelta(hours=10))]
        self.assertIn(MATCH_REMINDER_JOB, soon)
        self.assertEqual([kind for kind, _, _ in follow_up_times(NOW, None)], [MATCH_CHECK_IN_JOB, MATCH_CHECK_IN_JOB])

    async def test_introduction_reaches_both_in_their_own_chat(self) -> None:
        meet_at = datetime.now(UTC) + timedelta(days=4)
        pair = await introduce_pair(self.pair["id"], place="Chai Point, Baner", when="Sunday 6pm", meet_at=meet_at, created_by="op")
        self.assertEqual(pair["status"], "introduced")
        self.assertEqual(pair["plan"]["place"], "Chai Point, Baner")
        for user_id in ("ua", "ub"):
            self.assertIsNotNone(get_agent_job(f"{MATCH_INTRO_JOB}:{user_id}:{pair['id']}"))
            self.assertIsNotNone(get_agent_job(f"{MATCH_REMINDER_JOB}:{user_id}:{pair['id']}:reminder"))
            self.assertIsNotNone(get_agent_job(f"{MATCH_CHECK_IN_JOB}:{user_id}:{pair['id']}:3"))
            self.assertIsNotNone(get_agent_job(f"{MATCH_CHECK_IN_JOB}:{user_id}:{pair['id']}:30"))

        seen_instructions: list[str] = []

        async def generate(conversation, user_id, *, instructions, **kwargs):
            seen_instructions.append(instructions)
            return "So, there is someone I think you would get on with.<next_message>Bela, from your building."

        sent = AsyncMock(return_value=True)
        with patch("agent.proactive.service.generate_initiative_text", generate), patch("channels.whatsapp.send_whatsapp_message", sent):
            self.assertEqual(await JobWorker().run_once(), 2)  # only the two intros are due

        for user_id, chat in (("ua", "ua-whatsapp"), ("ub", "ub-web")):
            messages = get_conversation(chat, user_id)["messages"]
            self.assertEqual([m["content"] for m in messages[-2:]], ["So, there is someone I think you would get on with.", "Bela, from your building."])
            self.assertEqual(messages[-1]["match_pair_id"], pair["id"])
            self.assertEqual(messages[-1]["proactive_kind"], "match_intro")
        self.assertEqual(sent.await_count, 2)
        self.assertEqual(sent.await_args_list[0].args[0], "ua-phone")
        told = get_match_pair(pair["id"])["plan"]["told"]
        self.assertTrue(told["ua"]["sent"] and told["ub"]["sent"])
        # The model got the facts, nothing more: the other's first name, the reasons, the plan; never the private line.
        self.assertIn("Bela", seen_instructions[0])
        self.assertIn("dry humour", seen_instructions[0])
        self.assertIn("Chai Point, Baner, Sunday 6pm", seen_instructions[0])
        self.assertIn("Aman", seen_instructions[1])

        # In a normal turn Omi now knows about the introduction, and the outcome tool is on.
        sources = match_hosting_sources("ua")
        self.assertEqual(len(sources), 1)
        self.assertIn(f"Bela (pair id {pair['id']})", sources[0]["content"])
        self.assertIn("Chai Point, Baner, Sunday 6pm", sources[0]["content"])
        self.assertIn("record_match_outcome", [t["function"]["name"] for t in tool_specs(ToolContext("ua", "ua-whatsapp"))])
        self.assertNotIn("record_match_outcome", [t["function"]["name"] for t in tool_specs(ToolContext("uc", "x"))])

        results = await run_calls([ToolCall("record_match_outcome", {"pair_id": pair["id"], "outcome": "met", "note": "went well"})], ToolContext("ua", "ua-whatsapp"))
        self.assertEqual(results[0].trace["outcome"], "met")
        after = get_match_pair(pair["id"])
        self.assertEqual(after["status"], "met")
        self.assertEqual(after["plan"]["outcomes"][0]["note"], "went well")
        self.assertIn("they met", match_hosting_sources("ua")[0]["content"])
        wrong = await run_calls([ToolCall("record_match_outcome", {"pair_id": pair["id"], "outcome": "met"})], ToolContext("uc", "x"))
        self.assertEqual(wrong[0].trace["error"], "unknown_tool")  # off for a user with no introduction

    async def test_nothing_goes_out_for_a_closed_pair_and_check_ins_wait_for_daytime(self) -> None:
        pair = await introduce_pair(self.pair["id"], created_by="op")
        generate = AsyncMock(return_value="How did it go?")
        job = {"id": "j", "kind": MATCH_CHECK_IN_JOB, "user_id": "ub", "conversation_id": "ub-web", "payload": {"pair_id": pair["id"], "day": 3}}
        with patch("agent.proactive.service.generate_initiative_text", generate):
            with patch("agent.matching.hosting.utc_now", return_value=datetime(2026, 11, 5, 23, 30, tzinfo=UTC)):
                self.assertFalse(await run_match_check_in_job(job))  # 05:00 in India: waits for the morning
            self.assertIsNotNone(get_agent_job(f"{MATCH_CHECK_IN_JOB}:ub:{pair['id']}:3"))
            generate.assert_not_awaited()
            with patch("agent.matching.hosting.utc_now", return_value=datetime(2026, 11, 5, 9, 0, tzinfo=UTC)):
                self.assertTrue(await run_match_check_in_job(job))
            self.assertEqual(get_conversation("ub-web", "ub")["messages"][-1]["proactive_kind"], "match_check_in_3")
            # The user was never told by the intro job here, so the outcome tool is off for them; the operator records it.
            set_match_pair_status(pair["id"], "declined")
            generate.reset_mock()
            with patch("agent.matching.hosting.utc_now", return_value=datetime(2026, 11, 5, 9, 0, tzinfo=UTC)):
                self.assertFalse(await run_match_check_in_job(job))
            generate.assert_not_awaited()
        self.assertEqual(match_hosting_sources("ub"), [])  # declined and the user was never told: nothing to say

    def test_operator_endpoint(self) -> None:
        with patch.dict(os.environ, {"AUTH_REQUIRED": "false", "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "true"}):
            client = TestClient(app)
            self.assertEqual(client.post(f"/api/admin/pairs/{self.pair['id']}/introduce", json={"place": "x", "meet_at": "2027-01-01T18:00:00"}).status_code, 400)
            response = client.post(f"/api/admin/pairs/{self.pair['id']}/introduce", json={"place": "Chai Point", "when": "Sunday 6pm", "meet_at": "2027-01-03T18:00:00+05:30"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "introduced")
            self.assertEqual(client.post(f"/api/admin/pairs/{self.pair['id']}/introduce", json={}).status_code, 409)
            self.assertEqual(client.post("/api/admin/pairs/nope/introduce", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
