"""A batch that keeps failing on its content is skipped; outages and deleted chats are not failures."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.service import MAX_BATCH_CONTENT_FAILURES, run_background_cognition
from agent.memory_engine.processing import get_processing_state
from storage import delete_conversation, list_agent_memories, reset_db, save_conversation

USER = "batch-recovery-user"
CHAT = "batch-recovery-chat"
MESSAGES = [{"role": "user", "content": "I moved to Pune last month for a new job."}]
VALID = {
    "decision": "no_change",
    "operations": [],
    "thread_operation": {"operation": "none"},
    "handoff": {"summary": "", "active_people": [], "active_topics": [], "unresolved_references": []},
}


class BatchRecoveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CHAT, "status": "active", "messages": MESSAGES}, USER)
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    async def _run(self, **provider) -> dict:
        with patch(
            "agent.cognition.background.service.analyze_background_cognition",
            new_callable=AsyncMock,
            **provider,
        ):
            return await run_background_cognition(CHAT, USER, MESSAGES)

    def _cursor(self) -> int:
        state = get_processing_state(CHAT, USER)
        return state.processed_through_message_index if state else -1

    async def test_a_batch_failing_on_its_content_is_skipped_after_a_few_tries(self) -> None:
        malformed = {**VALID, "operations": "not a list"}
        for attempt in range(1, MAX_BATCH_CONTENT_FAILURES):
            result = await self._run(return_value=malformed)
            self.assertEqual(result["status"], "live_invalid")
            self.assertEqual(result["failed_attempts"], attempt)
            self.assertEqual(self._cursor(), -1)

        result = await self._run(return_value=malformed)

        self.assertEqual(result["status"], "skipped_after_failures")
        self.assertEqual(self._cursor(), 0)
        self.assertEqual(list_agent_memories(USER), [])
        # Nothing left pending, so the next run does nothing.
        self.assertEqual((await self._run(return_value=VALID))["status"], "no_pending_messages")

    async def test_provider_outages_never_count_toward_skipping(self) -> None:
        for _ in range(MAX_BATCH_CONTENT_FAILURES + 2):
            result = await self._run(side_effect=TimeoutError("provider slow"))
            self.assertEqual(result["status"], "live_error")
            self.assertNotIn("failed_attempts", result)
        self.assertEqual(self._cursor(), -1)

        self.assertNotIn((await self._run(return_value=VALID))["status"], {"live_error", "live_invalid"})
        self.assertEqual(self._cursor(), 0)

    async def test_a_chat_deleted_while_waiting_is_not_a_failure(self) -> None:
        async def delete_then_answer(*_args, **_kwargs):
            delete_conversation(CHAT, USER)
            return VALID

        with patch(
            "agent.cognition.background.service.analyze_background_cognition",
            side_effect=delete_then_answer,
        ):
            result = await run_background_cognition(CHAT, USER, MESSAGES)

        self.assertEqual(result["status"], "conversation_unavailable")


if __name__ == "__main__":
    unittest.main()
