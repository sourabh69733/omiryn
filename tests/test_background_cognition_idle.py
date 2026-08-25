"""Verifies the in-process idle debounce around background cognition."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.idle import IdleCognitionScheduler
from storage import reset_db, save_conversation


class IdleCognitionSchedulerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.user_id = "idle-user"
        self.conversation_id = "idle-conversation"
        self.rollout = patch.dict(
            os.environ,
            {
                "AGENT_PIPELINE_VERSION": "v2",
                "AGENT_ROLLOUT": "shadow",
            },
        )
        self.rollout.start()

    async def asyncTearDown(self) -> None:
        scheduler = getattr(self, "scheduler", None)
        if scheduler is not None:
            await scheduler.shutdown()
        self.rollout.stop()

    async def test_idle_flush_reloads_and_processes_fresh_conversation(self) -> None:
        messages = self._messages("I want a calm partner.")
        self._save(messages)
        self.scheduler = IdleCognitionScheduler(delay_seconds=0)

        with patch(
            "agent.cognition.background.idle.run_background_cognition",
            new_callable=AsyncMock,
            return_value={"status": "shadow_valid"},
        ) as run:
            task = self.scheduler.schedule(
                self.conversation_id,
                self.user_id,
                expected_message_count=len(messages),
            )
            await task

        run.assert_awaited_once_with(
            self.conversation_id,
            self.user_id,
            messages,
            "memory-model",
        )

    async def test_new_activity_replaces_previous_idle_timer(self) -> None:
        first_messages = self._messages("I want a calm partner.")
        self._save(first_messages)
        self.scheduler = IdleCognitionScheduler(delay_seconds=60)

        first = self.scheduler.schedule(
            self.conversation_id,
            self.user_id,
            expected_message_count=len(first_messages),
        )
        second_messages = first_messages + self._messages("Humour matters too.")
        self._save(second_messages)
        second = self.scheduler.schedule(
            self.conversation_id,
            self.user_id,
            expected_message_count=len(second_messages),
        )
        await asyncio.sleep(0)

        self.assertTrue(first.cancelled())
        self.assertFalse(second.done())

    async def test_stale_timer_does_not_process_newer_messages(self) -> None:
        messages = self._messages("I want a calm partner.")
        self._save(messages + self._messages("Humour matters too."))
        self.scheduler = IdleCognitionScheduler(delay_seconds=0)

        with patch(
            "agent.cognition.background.idle.run_background_cognition",
            new_callable=AsyncMock,
        ) as run:
            task = self.scheduler.schedule(
                self.conversation_id,
                self.user_id,
                expected_message_count=len(messages),
            )
            await task

        run.assert_not_awaited()

    async def test_flush_now_cancels_timer_and_runs_session_end_batch(self) -> None:
        messages = self._messages("I want a calm partner.")
        self._save(messages, status="extracted")
        self.scheduler = IdleCognitionScheduler(delay_seconds=60)
        timer = self.scheduler.schedule(
            self.conversation_id,
            self.user_id,
            expected_message_count=len(messages),
        )

        with patch(
            "agent.cognition.background.idle.run_background_cognition",
            new_callable=AsyncMock,
            return_value={"status": "shadow_valid"},
        ) as run:
            result = await self.scheduler.flush_now(self.conversation_id, self.user_id)

        self.assertTrue(timer.cancelled())
        self.assertEqual(result["status"], "shadow_valid")
        run.assert_awaited_once_with(
            self.conversation_id,
            self.user_id,
            messages,
            "memory-model",
        )

    def _save(self, messages: list[dict[str, object]], *, status: str = "active") -> None:
        save_conversation(
            {
                "id": self.conversation_id,
                "status": status,
                "agent_model": "memory-model",
                "messages": messages,
            },
            self.user_id,
        )

    @staticmethod
    def _messages(user_text: str) -> list[dict[str, object]]:
        return [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": "Tell me more."},
        ]
