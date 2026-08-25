"""Debounces sub-threshold cognition and flushes it when a chat session ends."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from storage import get_conversation

from .service import (
    background_cognition_enabled,
    run_background_cognition,
    should_schedule_idle_background_cognition,
)


DEFAULT_IDLE_FLUSH_SECONDS = 120.0
logger = logging.getLogger(__name__)
SchedulerKey = tuple[str, str]


class IdleCognitionScheduler:
    """Owns one replaceable in-process idle timer per user conversation."""

    def __init__(self, *, delay_seconds: float = DEFAULT_IDLE_FLUSH_SECONDS) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        self._delay_seconds = delay_seconds
        self._tasks: dict[SchedulerKey, asyncio.Task[dict[str, Any]]] = {}

    def schedule(
        self,
        conversation_id: str,
        user_id: str,
        *,
        expected_message_count: int,
    ) -> asyncio.Task[dict[str, Any]]:
        """Replace the conversation timer and return the new task for observability."""
        key = (conversation_id, user_id)
        self.cancel(conversation_id, user_id)
        task = asyncio.create_task(
            self._wait_and_flush(
                key,
                expected_message_count=expected_message_count,
            ),
            name=f"idle-cognition:{conversation_id}",
        )
        self._tasks[key] = task
        return task

    def cancel(
        self,
        conversation_id: str,
        user_id: str,
    ) -> asyncio.Task[dict[str, Any]] | None:
        """Cancel and forget a pending timer without touching cognition state."""
        task = self._tasks.pop((conversation_id, user_id), None)
        if task is not None and not task.done():
            task.cancel()
        return task

    async def flush_now(self, conversation_id: str, user_id: str) -> dict[str, Any]:
        """Cancel the idle wait and flush current durable messages immediately."""
        timer = self.cancel(conversation_id, user_id)
        if timer is not None and timer is not asyncio.current_task():
            await asyncio.gather(timer, return_exceptions=True)
        if not background_cognition_enabled():
            return {"status": "disabled", "operation_count": 0}
        return await self._flush_fresh(conversation_id, user_id)

    async def shutdown(self) -> None:
        """Cancel all timers so application shutdown does not leak tasks."""
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _wait_and_flush(
        self,
        key: SchedulerKey,
        *,
        expected_message_count: int,
    ) -> dict[str, Any]:
        try:
            await asyncio.sleep(self._delay_seconds)
            conversation_id, user_id = key
            conversation = get_conversation(conversation_id, user_id)
            if conversation is None or conversation.get("status") != "active":
                return {"status": "conversation_unavailable", "operation_count": 0}
            messages = list(conversation.get("messages") or [])
            if len(messages) != expected_message_count:
                return {"status": "stale_timer", "operation_count": 0}
            if not should_schedule_idle_background_cognition(
                conversation_id,
                user_id,
                messages,
                True,
            ):
                return {"status": "no_pending_messages", "operation_count": 0}
            return await run_background_cognition(
                conversation_id,
                user_id,
                messages,
                conversation.get("agent_model"),
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception(
                "agent.idle_cognition_failed conversation_id=%s user_id=%s",
                key[0],
                key[1],
            )
            return {
                "status": "scheduler_error",
                "operation_count": 0,
                "errors": [f"{type(error).__name__}: {str(error)[:300]}"],
            }
        finally:
            if self._tasks.get(key) is asyncio.current_task():
                self._tasks.pop(key, None)

    async def _flush_fresh(self, conversation_id: str, user_id: str) -> dict[str, Any]:
        conversation = get_conversation(conversation_id, user_id)
        if conversation is None:
            return {"status": "conversation_unavailable", "operation_count": 0}
        return await run_background_cognition(
            conversation_id,
            user_id,
            list(conversation.get("messages") or []),
            conversation.get("agent_model"),
        )


idle_cognition_scheduler = IdleCognitionScheduler()


__all__ = [
    "DEFAULT_IDLE_FLUSH_SECONDS",
    "IdleCognitionScheduler",
    "idle_cognition_scheduler",
]
