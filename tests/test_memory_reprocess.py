"""Reprocessing: chats handled by the old pipeline get a v3 pass; dry run touches nothing."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.reprocess import chats_needing_v3, reprocess_conversation
from agent.memory_engine.processing import MemoryProcessingState, get_processing_state, save_processing_state
from storage import reset_db, save_conversation
from storage.profile_facts import save_data_point_extraction_debug

USER = "reprocess-user"
MESSAGES = [
    {"role": "user", "content": "I play badminton every evening with hostel friends."},
    {"role": "assistant", "content": "Every evening is commitment!"},
    {"role": "user", "content": "And I shoot street photos on weekends."},
]
NO_CHANGE = {
    "decision": "no_change",
    "operations": [],
    "thread_operation": {"operation": "none"},
    "handoff": {"summary": "", "active_people": [], "active_topics": [], "unresolved_references": []},
}


def chat(conversation_id: str, processed_through: int | None = None) -> None:
    save_conversation({"id": conversation_id, "status": "active", "messages": MESSAGES}, USER)
    if processed_through is not None:
        save_processing_state(
            MemoryProcessingState(
                conversation_id=conversation_id,
                user_id=USER,
                processed_through_message_index=processed_through,
            )
        )


def v3_ran_on(conversation_id: str) -> None:
    save_data_point_extraction_debug(
        {
            "user_id": USER,
            "source_kind": "agent_conversation",
            "source_id": conversation_id,
            "candidate_key": f"background_cognition:{conversation_id}:no_change",
            "decision": "no_change",
            "candidate": {},
            "review": {},
            "metadata": {"extractor": "background_cognition_v3"},
        }
    )


class ReprocessTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_only_chats_marked_done_without_a_v3_run_need_it(self) -> None:
        chat("v2-era", processed_through=2)
        chat("v3-done", processed_through=2)
        v3_ran_on("v3-done")
        chat("never-processed")  # the catch-up handles these

        self.assertEqual([row["id"] for row in chats_needing_v3(USER)], ["v2-era"])

    async def test_dry_run_leaves_the_cursor(self) -> None:
        chat("v2-era", processed_through=2)
        conversation = chats_needing_v3(USER)[0]

        result = await reprocess_conversation(conversation, USER)

        self.assertEqual(result["status"], "would_reprocess")
        self.assertEqual(get_processing_state("v2-era", USER).processed_through_message_index, 2)

    async def test_apply_runs_v3_over_the_whole_chat(self) -> None:
        chat("v2-era", processed_through=2)
        conversation = chats_needing_v3(USER)[0]
        with patch(
            "agent.cognition.background.service.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=NO_CHANGE,
        ) as provider:
            result = await reprocess_conversation(conversation, USER, apply=True)

        self.assertEqual(result["status"], "done")
        self.assertGreaterEqual(provider.await_count, 1)
        self.assertEqual(get_processing_state("v2-era", USER).processed_through_message_index, 2)
        self.assertEqual(chats_needing_v3(USER), [])

    async def test_a_provider_outage_stops_and_leaves_it_partial(self) -> None:
        chat("v2-era", processed_through=2)
        conversation = chats_needing_v3(USER)[0]
        with patch(
            "agent.cognition.background.service.analyze_background_cognition",
            new_callable=AsyncMock,
            side_effect=TimeoutError("slow"),
        ):
            result = await reprocess_conversation(conversation, USER, apply=True)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["statuses"], ["live_error"])


if __name__ == "__main__":
    unittest.main()
