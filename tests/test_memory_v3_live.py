"""Verifies version-only live v3 extraction using the existing cognition call."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.service import run_background_cognition
from agent.memory_engine.processing import get_processing_state
from storage import (
    list_agent_memories,
    list_profile_facts,
    reset_db,
    save_conversation,
)


class MemoryV3LiveTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "memory-v3-live-user"
        self.conversation_id = "memory-v3-live-conversation"
        self.messages = [
            {
                "role": "user",
                "content": "I build a matchmaking product called Omiryn.",
            }
        ]
        save_conversation(
            {
                "id": self.conversation_id,
                "status": "active",
                "messages": self.messages,
            },
            self.user_id,
        )

    async def test_v3_writes_canonical_memory_once_without_v2_data_point(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"AGENT_PIPELINE_VERSION": "v3", "AGENT_ROLLOUT": "off"},
                clear=True,
            ),
            patch(
                "agent.cognition.background.service.embed_memory_query",
                new_callable=AsyncMock,
                return_value={
                    "provider": "deepinfra",
                    "model": "multilingual",
                    "dimensions": 2,
                    "values": [1.0, 0.0],
                },
            ) as embed_query,
            patch(
                "agent.cognition.background.service.analyze_background_cognition",
                new_callable=AsyncMock,
                return_value=self._valid_response(),
            ) as provider,
            patch(
                "agent.cognition.background.service.index_agent_memories",
                new_callable=AsyncMock,
                return_value=1,
            ) as index_memories,
        ):
            first = await run_background_cognition(
                self.conversation_id,
                self.user_id,
                self.messages,
                model="test-model",
            )
            repeated = await run_background_cognition(
                self.conversation_id,
                self.user_id,
                self.messages,
                model="test-model",
            )

        memories = list_agent_memories(self.user_id)
        self.assertEqual(first["status"], "live_applied", first)
        self.assertEqual(first["applied_count"], 1)
        self.assertEqual(repeated["status"], "no_pending_messages")
        self.assertEqual(provider.await_count, 1)
        self.assertEqual(provider.await_args.kwargs["memory_version"], 3)
        embed_query.assert_awaited_once_with(
            "I build a matchmaking product called Omiryn.",
            conversation_id=self.conversation_id,
        )
        index_memories.assert_awaited_once()
        self.assertEqual(
            index_memories.await_args.kwargs["conversation_id"], self.conversation_id
        )
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["kind"], "semantic")
        self.assertEqual(memories[0]["purposes"], ["profile"])
        self.assertEqual(memories[0]["key"], "work.product")
        self.assertEqual(memories[0]["allowed_uses"], ["reply_context"])
        self.assertEqual(memories[0]["evidence"][0]["message_index"], 0)
        self.assertEqual(list_profile_facts(self.user_id), [])

    async def test_invalid_v3_evidence_does_not_write_or_advance_cursor(self) -> None:
        response = self._valid_response()
        response["operations"][0]["evidence_message_indexes"] = [99]
        with (
            patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"}, clear=True),
            patch(
                "agent.cognition.background.service.analyze_background_cognition",
                new_callable=AsyncMock,
                return_value=response,
            ),
        ):
            result = await run_background_cognition(
                self.conversation_id,
                self.user_id,
                self.messages,
            )

        self.assertEqual(result["status"], "live_invalid")
        self.assertEqual(list_agent_memories(self.user_id), [])
        self.assertIsNone(get_processing_state(self.conversation_id, self.user_id))

    async def test_retry_after_cursor_failure_reuses_committed_memory_batch(self) -> None:
        environment = {"AGENT_PIPELINE_VERSION": "v3"}
        with (
            patch.dict(os.environ, environment, clear=True),
            patch(
                "agent.cognition.background.service.analyze_background_cognition",
                new_callable=AsyncMock,
                return_value=self._valid_response(),
            ),
            patch(
                "agent.cognition.background.service.save_processing_state",
                side_effect=RuntimeError("cursor write failed"),
            ),
        ):
            failed = await run_background_cognition(
                self.conversation_id,
                self.user_id,
                self.messages,
            )

        with (
            patch.dict(os.environ, environment, clear=True),
            patch(
                "agent.cognition.background.service.analyze_background_cognition",
                new_callable=AsyncMock,
                return_value=self._valid_response(),
            ),
        ):
            retried = await run_background_cognition(
                self.conversation_id,
                self.user_id,
                self.messages,
            )

        self.assertEqual(failed["status"], "live_error")
        self.assertEqual(retried["status"], "live_applied")
        self.assertTrue(retried["idempotent"])
        self.assertEqual(len(list_agent_memories(self.user_id)), 1)

    def _valid_response(self) -> dict[str, object]:
        return {
            "decision": "propose",
            "operations": [
                {
                    "operation": "add",
                    "memory_kind": "semantic",
                    "purposes": ["profile"],
                    "key": "work.product",
                    "value": {"name": "Omiryn", "role": "builder"},
                    "sensitivity": "standard",
                    "confidence": 0.95,
                    "importance": 0.7,
                    "occurred_at": None,
                    "valid_from": None,
                    "valid_until": None,
                    "evidence_message_indexes": [0],
                }
            ],
            "thread_operation": {"operation": "none"},
            "handoff": {
                "summary": "The user builds Omiryn.",
                "active_people": [],
                "active_topics": ["work"],
                "unresolved_references": [],
            },
        }


if __name__ == "__main__":
    unittest.main()
