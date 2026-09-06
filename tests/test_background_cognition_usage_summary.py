"""Verifies user-visible output counts on background cognition usage events."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.service import run_background_cognition
from storage import list_agent_usage_events, reset_db, save_agent_usage_event, save_conversation


class BackgroundCognitionUsageSummaryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "cognition-usage-user"
        self.conversation_id = "cognition-usage-conversation"
        self.messages = [{"role": "user", "content": "I enjoy quiet Sunday mornings."}]
        save_conversation(
            {
                "id": self.conversation_id,
                "status": "active",
                "messages": self.messages,
            },
            self.user_id,
        )

    async def test_background_usage_event_includes_applied_result_counts(self) -> None:
        with patch.dict(
            os.environ,
            {"AGENT_PIPELINE_VERSION": "v3", "AGENT_PROVIDER": "mock"},
            clear=True,
        ):
            result = await run_background_cognition(
                self.conversation_id,
                self.user_id,
                self.messages,
                model="mock",
            )

        events = list_agent_usage_events(self.conversation_id, self.user_id)
        self.assertEqual(result["status"], "no_change")
        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0]["result_summary"],
            {
                "status": "no_change",
                "memory_operations": 0,
                "memories_applied": 0,
                "memories_deferred": 0,
                "thread_operations_applied": 0,
            },
        )
        self.assertEqual(
            events[0]["raw_usage"]["result_summary"],
            {
                "status": "no_change",
                "memory_operations": 0,
                "memories_applied": 0,
                "memories_deferred": 0,
                "thread_operations_applied": 0,
            },
        )


    async def test_missing_new_usage_event_does_not_overwrite_an_older_call(self) -> None:
        save_agent_usage_event(
            {
                "user_id": self.user_id,
                "conversation_id": self.conversation_id,
                "request_kind": "background_cognition",
                "provider": "mock",
                "model": "old-model",
                "success": True,
                "raw_usage": {},
            }
        )
        with (
            patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"}, clear=True),
            patch(
                "agent.cognition.background.service.analyze_background_cognition",
                new_callable=AsyncMock,
                return_value={
                    "decision": "no_change",
                    "operations": [],
                    "thread_operation": {"operation": "none"},
                    "handoff": {"summary": "", "active_people": [], "active_topics": [], "unresolved_references": []},
                },
            ),
        ):
            await run_background_cognition(
                self.conversation_id, self.user_id, self.messages, model="mock"
            )

        events = list_agent_usage_events(self.conversation_id, self.user_id)
        self.assertIsNone(events[0]["result_summary"])


if __name__ == "__main__":
    unittest.main()
