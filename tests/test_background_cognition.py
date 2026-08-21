"""Verifies the combined background contract without testing model wording."""

from __future__ import annotations

import importlib
import json
import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.conversation_engine.state import create_thread
from agent.memory_engine.processing import build_memory_batch
from storage import reset_db, save_conversation


class BackgroundCognitionTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "cognition-user"
        self.conversation_id = "cognition-conversation"
        self.messages = [
            {"role": "user", "content": "I am still worried about changing careers."},
            {"role": "assistant", "content": "The uncertainty sounds difficult."},
            {"role": "user", "content": "I need financial stability in my next role."},
        ]
        save_conversation(
            {
                "id": self.conversation_id,
                "status": "active",
                "messages": self.messages,
            },
            self.user_id,
        )

    def test_prompt_contains_one_shared_batch_with_memory_and_thread_candidates(self) -> None:
        module = importlib.import_module("agent.cognition.background.prompt")
        function = getattr(module, "background_cognition_prompt", None)
        self.assertTrue(callable(function), "background_cognition_prompt is missing")
        batch = self._batch()
        payload = json.loads(
            function(
                batch,
                existing_memories=[
                    {
                        "id": "memory-1",
                        "data_point_type": "matching_fact",
                        "category": "career",
                        "key": "stability",
                        "label": "Values financial stability",
                        "value": "financial stability",
                        "confidence": 0.9,
                    }
                ],
                thread_candidates=[self._thread_candidate("thread-1")],
            )
        )

        self.assertEqual(payload["conversation_id"], self.conversation_id)
        self.assertEqual(len(payload["messages"]), 3)
        self.assertEqual(payload["existing_memories"][0]["id"], "memory-1")
        self.assertEqual(payload["existing_threads"][0]["id"], "thread-1")

    def test_validator_accepts_memory_and_one_candidate_thread_operation(self) -> None:
        thread = create_thread(
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            title="Career change",
            summary="The user is considering changing careers.",
            origin="user_started",
        )
        module = importlib.import_module("agent.cognition.background.validation")
        function = getattr(module, "validate_background_cognition_analysis", None)
        self.assertTrue(
            callable(function), "validate_background_cognition_analysis is missing"
        )
        result = function(
            self._analysis(thread.id),
            batch=self._batch(),
            existing_memory_ids=set(),
            thread_candidates=[self._thread_candidate(thread.id)],
        )

        self.assertTrue(result.valid)
        self.assertTrue(result.memory.valid)
        self.assertTrue(result.thread["valid"])
        self.assertEqual(result.thread_operation, "continue")

    def test_invalid_thread_lane_does_not_invalidate_valid_memory_lane(self) -> None:
        module = importlib.import_module("agent.cognition.background.validation")
        function = getattr(module, "validate_background_cognition_analysis", None)
        self.assertTrue(
            callable(function), "validate_background_cognition_analysis is missing"
        )
        result = function(
            self._analysis("invented-thread"),
            batch=self._batch(),
            existing_memory_ids=set(),
            thread_candidates=[],
        )

        self.assertFalse(result.valid)
        self.assertTrue(result.memory.valid)
        self.assertFalse(result.thread["valid"])
        self.assertEqual(len(result.memory.operations), 1)

    def _batch(self):
        batch = build_memory_batch(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            messages=self.messages,
        )
        self.assertIsNotNone(batch)
        return batch

    def _analysis(self, thread_id: str) -> dict[str, object]:
        return {
            "decision": "propose",
            "operations": [
                {
                    "operation": "add",
                    "target_memory_id": None,
                    "data_point_type": "matching_fact",
                    "category": "career",
                    "key": "stability",
                    "label": "Values financial stability",
                    "value": "financial stability",
                    "confidence": 0.9,
                    "evidence_message_indexes": [2],
                }
            ],
            "thread_operation": {
                "operation": "continue",
                "thread_id": thread_id,
                "summary": "The user connected career change with financial stability.",
                "depth": "explored",
            },
            "handoff": {
                "summary": "Career change remains unresolved.",
                "active_people": [],
                "active_topics": ["career change"],
                "unresolved_references": [],
            },
        }

    def _thread_candidate(self, thread_id: str) -> dict[str, object]:
        return {
            "id": thread_id,
            "user_id": self.user_id,
            "title": "Career change",
            "summary": "The user is considering changing careers.",
            "status": "open",
            "origin": "user_started",
            "active": True,
            "version": 1,
            "matching_dimension": None,
            "depth": "mentioned",
            "user_interest": "high",
            "salience": 0.8,
            "next_angle": None,
            "last_conversation_id": self.conversation_id,
        }
class BackgroundCognitionProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_provider_returns_one_decoded_combined_object(self) -> None:
        module = importlib.import_module("agent.providers.extraction.service")
        function = getattr(module, "analyze_background_cognition", None)
        self.assertTrue(callable(function), "analyze_background_cognition is missing")
        raw = {
            "decision": "no_change",
            "operations": [],
            "thread_operation": {"operation": "none"},
            "handoff": {
                "summary": "",
                "active_people": [],
                "active_topics": [],
                "unresolved_references": [],
            },
        }
        with (
            patch("agent.providers.extraction.service._provider_name", return_value="deepinfra"),
            patch(
                "agent.providers.extraction.service.provider_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(raw),
            ) as provider,
        ):
            result = await function("{}", conversation_id="conversation-1")

        self.assertEqual(result, raw)
        self.assertEqual(provider.await_count, 1)


if __name__ == "__main__":
    unittest.main()
