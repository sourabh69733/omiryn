"""The test-flow player: made-up people answer Omi's ask and write in the pair chat, so one real
person can test the flow. It plays only seeded ids, only inside a test group, never in production."""

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from agent.evals.matching.player import NotATestSetup, TEST_USER_PREFIX, pair_and_ask, persona_of, play_once, seeded_people, setup_test_pool
from storage import (
    add_match_message,
    create_match_pool,
    get_match_pair,
    join_match_pool,
    list_match_messages,
    match_chat_summaries,
    reset_db,
    save_conversation,
    save_match_pair,
    save_user_profile,
    update_match_pair_plan,
)

AARAV = f"{TEST_USER_PREFIX}aarav-1a2b3c4d"
KABIR = f"{TEST_USER_PREFIX}kabir-5e6f7a8b"
ME = "real-user"
DAY = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
CHECK = {"fit": "yes", "reasons": [{"source": "area:humor", "area": "humor", "text": "Both like dry humour."}], "icebreaker": "Ask about misal.", "score": 60}


def _user(user_id: str, name: str) -> None:
    save_user_profile(user_id, "male", "unknown", display_name=name)
    save_conversation({"id": f"{user_id}-web", "status": "active", "messages": [{"role": "user", "content": "hi", "created_at": "2026-10-20T10:00:00+00:00"}]}, user_id)


def _told(pair_id: str, *user_ids: str) -> None:
    def told(plan: dict) -> dict:
        for user_id in user_ids:
            plan.setdefault("told", {})[user_id] = {"at": DAY.isoformat(), "sent": True}
        return plan

    update_match_pair_plan(pair_id, told)


class PlayerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PROVIDER": "mock", "AUTH_REQUIRED": "false", "APP_ENV": "test"})
        self.env.start()
        _user(AARAV, "Aarav")
        _user(KABIR, "Kabir")
        _user(ME, "Sourabh Test")
        self.publish = patch("realtime.realtime_hub.publish", new=AsyncMock(return_value=0))
        self.published = self.publish.start()
        self.pool = setup_test_pool()["pool"]
        join_match_pool(ME, self.pool["join_code"])

    def tearDown(self) -> None:
        self.publish.stop()
        self.env.stop()

    def test_only_seeded_ids_are_made_up_people(self) -> None:
        self.assertEqual(persona_of(AARAV).name, "Aarav")
        self.assertIsNone(persona_of(ME))
        self.assertIsNone(persona_of(f"{TEST_USER_PREFIX}nobody-12345678"))
        self.assertEqual(seeded_people(), [AARAV, KABIR])
        again = setup_test_pool()  # the same group, nobody added twice
        self.assertEqual((again["pool"]["id"], again["people"]), (self.pool["id"], [AARAV, KABIR]))

    async def test_says_yes_then_answers_in_the_chat(self) -> None:
        with patch("agent.matching.pool.check_compatibility", new=AsyncMock(return_value=type("C", (), {"as_dict": lambda self: CHECK})())):
            pair = await pair_and_ask(self.pool["id"], ME, "aarav")
        self.assertEqual(pair["status"], "asked")
        # Omi has not told Aarav yet: nothing to answer.
        self.assertEqual(await play_once(self.pool["id"]), [])
        _told(pair["id"], AARAV, ME)
        actions = await play_once(self.pool["id"])
        self.assertEqual([(a.user_id, a.kind) for a in actions], [(AARAV, "answered")])
        self.assertEqual(get_match_pair(pair["id"])["plan"]["answers"][AARAV]["answer"], "accept")
        # The tester says hi too: introduced, the chat opens, and Aarav waits for the first message.
        from agent.matching.asking import record_answer

        self.assertEqual(record_answer(pair["id"], ME, "accept")["status"], "introduced")
        self.assertEqual(await play_once(self.pool["id"]), [])
        add_match_message(pair["id"], ME, "hey Aarav, Omi says you know the best misal")
        actions = await play_once(self.pool["id"])
        self.assertEqual([(a.user_id, a.kind) for a in actions], [(AARAV, "replied")])
        messages = list_match_messages(pair["id"])
        self.assertEqual([m["sender_id"] for m in messages], [ME, AARAV])
        self.assertEqual(match_chat_summaries([pair["id"]], ME)[pair["id"]]["unread"], 1)
        # Both screens are told, by id only; and Aarav does not write twice in a row.
        events = [call.args[0] for call in self.published.await_args_list]
        self.assertEqual({(e.type, e.scope_id) for e in events}, {("match.typing", ME), ("match.message", ME), ("match.message", AARAV)})
        self.assertEqual(await play_once(self.pool["id"]), [])

    async def test_a_pairing_with_nothing_in_common_is_not_asked(self) -> None:
        thin = {"fit": "unknown", "reasons": [], "why_not": "only 0 areas to compare; needs 3"}
        with patch("agent.matching.pool.check_compatibility", new=AsyncMock(return_value=type("C", (), {"as_dict": lambda self: thin})())):
            with self.assertRaises(NotATestSetup) as refused:
                await pair_and_ask(self.pool["id"], ME, "aarav")
        self.assertIn("only 0 areas to compare", str(refused.exception))
        from storage import list_match_pairs

        self.assertEqual([p["status"] for p in list_match_pairs(self.pool["id"])], ["candidate"])

    def test_a_picture_reaches_the_persona_as_words(self) -> None:
        from agent.evals.matching.player import _words

        self.assertEqual(_words({"text": "hi", "image": None}), "hi")
        self.assertEqual(_words({"text": "", "image": {"content_type": "image/jpeg"}}), "[sent a picture, which you cannot see]")
        self.assertEqual(_words({"text": "look", "image": {"content_type": "image/gif"}}), "[sent a GIF, which you cannot see] look")

    async def test_other_endings_pass_silence_and_writing_first(self) -> None:
        pair = save_match_pair(self.pool["id"], ME, KABIR, CHECK, status="asked")
        _told(pair["id"], KABIR, ME)
        self.assertEqual(await play_once(self.pool["id"], answer="none"), [])
        self.assertEqual((await play_once(self.pool["id"], answer="pass"))[0].kind, "answered")
        self.assertEqual(get_match_pair(pair["id"])["status"], "declined")
        opened = save_match_pair(self.pool["id"], ME, AARAV, CHECK, status="introduced")
        self.assertEqual(await play_once(self.pool["id"]), [])
        self.assertEqual([(a.user_id, a.kind) for a in await play_once(self.pool["id"], open_first=True)], [(AARAV, "replied")])
        self.assertEqual([m["sender_id"] for m in list_match_messages(opened["id"])], [AARAV])

    async def test_refuses_real_groups_real_people_and_production(self) -> None:
        real = create_match_pool("Baner block A")
        join_match_pool(AARAV, real["join_code"])
        with self.assertRaises(NotATestSetup):
            await play_once(real["id"])
        with self.assertRaises(NotATestSetup):
            setup_test_pool("Baner block B")
        with self.assertRaises(NotATestSetup):
            await pair_and_ask(self.pool["id"], AARAV, "meera-not-here")
        # A real person in the test group is never played: their open chat gets no reply from the player.
        _user("real-two", "Other Tester")
        join_match_pool("real-two", self.pool["join_code"])
        pair = save_match_pair(self.pool["id"], ME, "real-two", CHECK, status="introduced")
        add_match_message(pair["id"], ME, "hello")
        self.assertEqual(await play_once(self.pool["id"]), [])
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            with self.assertRaises(NotATestSetup):
                await play_once(self.pool["id"])
            with self.assertRaises(NotATestSetup):
                setup_test_pool()


if __name__ == "__main__":
    unittest.main()
