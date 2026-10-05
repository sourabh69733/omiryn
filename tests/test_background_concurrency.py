"""Chats of one user write the shared cards one at a time, and no write overwrites another."""

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import update

from agent.cognition.background.service import run_background_cognition
from storage import get_vibe_card, reset_db, save_conversation, update_vibe_card
from storage import vibe_cards
from storage.database import ENGINE
from storage.memory_processing import claim_user_background_lease, release_user_background_lease
from storage.schema import memory_processing_leases

USER_ID = "concurrency-user"
FIRST = "concurrency-first"
SECOND = "concurrency-second"
MESSAGES = [
    {"role": "user", "content": "I love long walks and dark humor."},
    {"role": "assistant", "content": "Nice combo."},
    {"role": "user", "content": "And I want friends who don't flake."},
]


def line(text: str, conversation_id: str = FIRST) -> dict:
    return {
        "text": text,
        "evidence": [{"conversation_id": conversation_id, "message_index": 0, "sent_at": "2026-10-01T10:00:00+00:00"}],
    }


class UserLeaseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        for conversation_id in (FIRST, SECOND):
            save_conversation({"id": conversation_id, "status": "active", "messages": MESSAGES}, USER_ID)

    def test_one_chat_at_a_time_and_a_crashed_run_frees_the_lock(self) -> None:
        token = claim_user_background_lease(USER_ID, FIRST, lease_seconds=60)

        self.assertIsNotNone(token)
        self.assertIsNone(claim_user_background_lease(USER_ID, SECOND, lease_seconds=60))
        self.assertIsNotNone(claim_user_background_lease("someone-else", SECOND, lease_seconds=60))

        with ENGINE.begin() as connection:
            connection.execute(
                update(memory_processing_leases)
                .where(memory_processing_leases.c.batch_key == f"user:{USER_ID}")
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        taken = claim_user_background_lease(USER_ID, SECOND, lease_seconds=60)
        self.assertIsNotNone(taken)
        self.assertFalse(release_user_background_lease(USER_ID, token))
        self.assertTrue(release_user_background_lease(USER_ID, taken))

    async def test_a_second_chat_waits_while_the_first_is_running(self) -> None:
        token = claim_user_background_lease(USER_ID, FIRST, lease_seconds=60)
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_BACKGROUND_V2_THRESHOLD": "1"}), patch(
            "agent.cognition.background.service.analyze_background_cognition", new_callable=AsyncMock
        ) as provider:
            busy = await run_background_cognition(SECOND, USER_ID, MESSAGES)
            release_user_background_lease(USER_ID, token)
            provider.return_value = {
                "decision": "no_change",
                "operations": [],
                "thread_operation": {"operation": "none"},
                "handoff": {"summary": "", "active_people": [], "active_topics": [], "unresolved_references": []},
            }
            done = await run_background_cognition(SECOND, USER_ID, MESSAGES)

        self.assertEqual(busy["status"], "already_processing")
        self.assertEqual(provider.await_count, 1)
        self.assertNotEqual(done["status"], "already_processing")
        self.assertIsNotNone(claim_user_background_lease(USER_ID, FIRST, lease_seconds=60))


class VibeWriteRaceTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def test_a_write_that_lost_the_race_merges_again(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Likes dark humor.")})
        real_read = vibe_cards._read
        calls = 0

        def read_then_someone_else_writes(owner_id: str):
            nonlocal calls
            calls += 1
            stale = real_read(owner_id)
            if calls == 1:
                update_vibe_card(owner_id, {"social_energy": line("Calm, likes long walks.", SECOND)})
            return stale

        with patch("storage.vibe_cards._read", side_effect=read_then_someone_else_writes):
            update_vibe_card(USER_ID, {"friend_wish": line("Wants friends who don't flake.")})

        self.assertEqual(set(get_vibe_card(USER_ID)["areas"]), {"humor", "social_energy", "friend_wish"})


if __name__ == "__main__":
    unittest.main()
