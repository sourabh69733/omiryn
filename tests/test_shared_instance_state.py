"""State several server instances must agree on lives in the database, not in one process.

Presence (who has a chat open, and where), bursts of quick messages on messaging apps, and
delivery IDs already seen. A job that finds the user watching on another instance hands itself
over instead of saving a message that instance's socket would never push.
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import storage
from agent.jobs.worker import JobWorker
from agent.proactive import service as proactive_service
from agent.proactive.story import run_story_part_job
from agent.shared.clock import utc_now
from realtime.hub import InMemoryRealtimeHub
from storage import claim_channel_message, finish_burst, join_burst, list_conversations, reset_db

USER_ID = "shared-user"
CONVERSATION_ID = "shared-chat"


class _Socket:
    async def send_json(self, payload: dict) -> None:
        pass


async def _open_on(hub: InMemoryRealtimeHub) -> None:
    connection = await hub.register(_Socket(), USER_ID)
    await hub.subscribe(connection, "conversation", CONVERSATION_ID)


class PresenceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        reset_db()
        self.here = InMemoryRealtimeHub("instance-a")
        self.there = InMemoryRealtimeHub("instance-b")

    async def test_an_instance_sees_sockets_open_on_another(self) -> None:
        await _open_on(self.there)

        live = await self.here.live_everywhere()
        self.assertEqual(live, {(USER_ID, CONVERSATION_ID): {"instance-b"}})
        self.assertEqual(await self.here.live_conversations(), [])

    async def test_leaving_clears_the_row_and_a_stale_row_stops_counting(self) -> None:
        await _open_on(self.there)
        await self.there.reset()
        self.assertEqual(await self.here.live_everywhere(), {})

        storage.mark_live("instance-c", USER_ID, CONVERSATION_ID, now=utc_now())
        fresh = storage.live_conversations_everywhere(now=utc_now())
        later = storage.live_conversations_everywhere(now=utc_now().replace(year=utc_now().year + 1))
        self.assertIn((USER_ID, CONVERSATION_ID), fresh)
        self.assertEqual(later, {})

    async def test_watching_tells_here_from_elsewhere(self) -> None:
        with patch.object(proactive_service, "realtime_hub", self.here):
            self.assertIsNone(await proactive_service.watching(USER_ID, CONVERSATION_ID))
            await _open_on(self.there)
            self.assertEqual(await proactive_service.watching(USER_ID, CONVERSATION_ID), "elsewhere")
            await _open_on(self.here)
            self.assertEqual(await proactive_service.watching(USER_ID, CONVERSATION_ID), "here")


class HandOverTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()
        storage.save_conversation(
            {"id": CONVERSATION_ID, "status": "active", "messages": [{"role": "user", "content": "tell me a story"}, {"role": "assistant", "content": "Once...", "story": True}]},
            USER_ID,
        )
        self.here = InMemoryRealtimeHub("instance-a")
        self.there = InMemoryRealtimeHub("instance-b")

    async def asyncTearDown(self) -> None:
        self.env.stop()

    def _jobs(self) -> list[dict]:
        return storage.claim_due_agent_jobs(now=utc_now().replace(year=utc_now().year + 1), lease_seconds=1)

    async def test_a_story_part_is_handed_to_the_instance_with_the_socket(self) -> None:
        await _open_on(self.there)
        generate = AsyncMock(return_value="The next part.")
        with patch.object(proactive_service, "realtime_hub", self.here), patch("agent.proactive.story.generate_initiative_text", generate):
            sent = await run_story_part_job({"user_id": USER_ID, "conversation_id": CONVERSATION_ID})

        self.assertFalse(sent)
        generate.assert_not_awaited()
        self.assertEqual([job["kind"] for job in self._jobs()], ["story_part"])

    async def test_a_greeting_is_handed_over_too_and_runs_where_the_user_is(self) -> None:
        await _open_on(self.there)
        greet = AsyncMock(return_value=True)
        with patch.object(proactive_service, "realtime_hub", self.here), patch("agent.proactive.service.greet_on_return", greet):
            self.assertFalse(await proactive_service.run_return_greeting_job({"user_id": USER_ID, "conversation_id": CONVERSATION_ID}))
        greet.assert_not_awaited()
        self.assertEqual([job["kind"] for job in self._jobs()], ["return_greeting"])
        with patch.object(proactive_service, "realtime_hub", self.there), patch("agent.proactive.service.greet_on_return", greet):
            self.assertTrue(await proactive_service.run_return_greeting_job({"user_id": USER_ID, "conversation_id": CONVERSATION_ID}))
        greet.assert_awaited_once()


class BurstAndDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def test_one_replier_per_chat_and_a_late_message_keeps_the_burst_open(self) -> None:
        first = join_burst("telegram", "chat", "conv", now=utc_now(), lease_seconds=60)
        second = join_burst("telegram", "chat", "conv", now=utc_now(), lease_seconds=60)
        self.assertIsNotNone(first["token"])
        self.assertIsNone(second["token"])
        self.assertEqual(second["arrivals"], 2)
        # Answered one, but two arrived: the replier must go round again.
        self.assertFalse(finish_burst("telegram", "chat", first["token"], answered=1))
        self.assertTrue(finish_burst("telegram", "chat", first["token"], answered=2))
        self.assertIsNone(storage.burst_state("telegram", "chat"))

    def test_an_expired_lease_is_taken_over(self) -> None:
        first = join_burst("telegram", "chat", "conv", now=utc_now(), lease_seconds=0)
        second = join_burst("telegram", "chat", "conv", now=utc_now(), lease_seconds=60)
        self.assertIsNotNone(first["token"])
        self.assertIsNotNone(second["token"])
        self.assertFalse(finish_burst("telegram", "chat", first["token"], answered=2))

    def test_a_delivery_is_seen_once_across_instances(self) -> None:
        self.assertTrue(claim_channel_message("whatsapp", "wamid.1"))
        self.assertFalse(claim_channel_message("whatsapp", "wamid.1"))
        self.assertTrue(claim_channel_message("telegram", "wamid.1"))
        self.assertTrue(claim_channel_message("whatsapp", ""))


if __name__ == "__main__":
    unittest.main()
