"""Verifies live background cognition persists only validated thread operations."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.service import run_background_cognition
from agent.context_engine.conversation_engine.state import list_threads
from agent.memory_engine.processing import get_processing_state
from storage import reset_db, save_conversation


class BackgroundThreadLiveTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "background-thread-user"
        self.conversation_id = "background-thread-conversation"
        self.messages = [
            {"role": "user", "content": "I keep thinking about changing careers."},
            {"role": "assistant", "content": "What part keeps pulling you back?"},
            {"role": "user", "content": "I want meaningful work but stability matters."},
            {"role": "assistant", "content": "That tension sounds important."},
        ]
        save_conversation(
            {
                "id": self.conversation_id,
                "status": "active",
                "messages": self.messages,
            },
            self.user_id,
        )

    async def test_live_rollout_persists_validated_thread_before_cursor(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "AGENT_PIPELINE_VERSION": "v2",
                    "AGENT_ROLLOUT": "live",
                    "MEMORY_BACKGROUND_V2_THRESHOLD": "2",
                },
            ),
            patch(
                "agent.cognition.background.service.analyze_background_cognition",
                new_callable=AsyncMock,
                return_value=self._thread_analysis(),
            ),
        ):
            result = await run_background_cognition(
                self.conversation_id,
                self.user_id,
                self.messages,
            )

        threads = list_threads(self.user_id)
        self.assertEqual(result["thread_applied_count"], 1)
        self.assertFalse(result["thread_idempotent"])
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0].title, "Career change")
        self.assertIsNotNone(get_processing_state(self.conversation_id, self.user_id))

    async def test_thread_application_failure_does_not_advance_cursor(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "AGENT_PIPELINE_VERSION": "v2",
                    "AGENT_ROLLOUT": "live",
                    "MEMORY_BACKGROUND_V2_THRESHOLD": "2",
                },
            ),
            patch(
                "agent.cognition.background.service.analyze_background_cognition",
                new_callable=AsyncMock,
                return_value=self._thread_analysis(),
            ),
            patch(
                "agent.cognition.background.service.apply_validated_thread_proposal",
                side_effect=RuntimeError("thread database unavailable"),
                create=True,
            ),
        ):
            result = await run_background_cognition(
                self.conversation_id,
                self.user_id,
                self.messages,
            )

        self.assertEqual(result["status"], "live_error")
        self.assertEqual(list_threads(self.user_id), [])
        self.assertIsNone(get_processing_state(self.conversation_id, self.user_id))

    async def test_cursor_failure_retry_does_not_duplicate_committed_thread(self) -> None:
        environment = {
            "AGENT_PIPELINE_VERSION": "v2",
            "AGENT_ROLLOUT": "live",
            "MEMORY_BACKGROUND_V2_THRESHOLD": "2",
        }
        with (
            patch.dict("os.environ", environment),
            patch(
                "agent.cognition.background.service.analyze_background_cognition",
                new_callable=AsyncMock,
                return_value=self._thread_analysis(),
            ),
            patch(
                "agent.cognition.background.service.save_processing_state",
                side_effect=RuntimeError("cursor database unavailable"),
            ),
        ):
            first_result = await run_background_cognition(
                self.conversation_id,
                self.user_id,
                self.messages,
            )

        self.assertEqual(first_result["status"], "live_error")
        self.assertEqual(len(list_threads(self.user_id)), 1)
        self.assertIsNone(get_processing_state(self.conversation_id, self.user_id))

        with (
            patch.dict("os.environ", environment),
            patch(
                "agent.cognition.background.service.analyze_background_cognition",
                new_callable=AsyncMock,
                return_value=self._thread_analysis(),
            ),
        ):
            retry_result = await run_background_cognition(
                self.conversation_id,
                self.user_id,
                self.messages,
            )

        self.assertEqual(retry_result["status"], "live_applied")
        self.assertEqual(retry_result["thread_applied_count"], 1)
        self.assertTrue(retry_result["thread_idempotent"])
        self.assertEqual(len(list_threads(self.user_id)), 1)
        self.assertIsNotNone(get_processing_state(self.conversation_id, self.user_id))

    @staticmethod
    def _thread_analysis() -> dict[str, object]:
        return {
            "decision": "propose",
            "operations": [],
            "thread_operation": {
                "operation": "create",
                "title": "Career change",
                "summary": "The user is weighing meaning against stability.",
                "started_at": 0,
                "evidence": [0, 2],
                "depth": "explored",
                "user_interest": "high",
                "salience": 0.9,
            },
            "handoff": {
                "summary": "Career change remains unresolved.",
                "active_people": [],
                "active_topics": ["career change"],
                "unresolved_references": [],
            },
        }


if __name__ == "__main__":
    unittest.main()
