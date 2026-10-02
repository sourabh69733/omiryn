"""Debounces sub-threshold cognition with a durable job that survives restarts.

Every new message pushes the job's run time back, so the flush happens once the chat has
been quiet for the idle delay. The job also backs up the threshold run: if that run is lost
to a crash, the flush still processes whatever is pending.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from agent.jobs.queue import cancel_job, schedule_job
from agent.memory_engine.processing.service import get_processing_state
from storage import get_conversation, list_conversations

from .service import (
    background_cognition_enabled,
    has_pending_background_cognition,
    run_background_cognition,
)

MEMORY_FLUSH_JOB = "memory_flush"
DEFAULT_IDLE_FLUSH_SECONDS = 120.0
# When another worker holds the batch lease, check back after it should have finished.
_BUSY_RETRY_SECONDS = 60.0
logger = logging.getLogger(__name__)


def idle_flush_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("MEMORY_IDLE_FLUSH_SECONDS", DEFAULT_IDLE_FLUSH_SECONDS)))
    except ValueError:
        return DEFAULT_IDLE_FLUSH_SECONDS


def schedule_idle_flush(conversation_id: str, user_id: str) -> None:
    """(Re)start the idle countdown for this conversation."""
    schedule_job(MEMORY_FLUSH_JOB, user_id, conversation_id, delay_seconds=idle_flush_seconds())


def request_flush_now(conversation_id: str, user_id: str) -> None:
    """Flush at the next worker pass, e.g. when the user ends the chat session."""
    schedule_job(MEMORY_FLUSH_JOB, user_id, conversation_id, delay_seconds=0)


def catch_up_pending(user_id: str) -> list[str]:
    """Queue a flush now for every chat of this user with unprocessed messages.

    Called when the user comes back. Background work only gets CPU while a request is running
    (Cloud Run with no always-on instance), so a flush that came due while nobody was online,
    or one that ran out of retries, runs now instead of waiting for new messages.
    """
    if not background_cognition_enabled():
        return []
    queued: list[str] = []
    for conversation in list_conversations(user_id):
        messages = list(conversation.get("messages") or [])
        if has_pending_background_cognition(conversation["id"], user_id, messages):
            request_flush_now(conversation["id"], user_id)
            queued.append(conversation["id"])
    if queued:
        logger.info("agent.memory_catch_up user_id=%s conversations=%s", user_id, len(queued))
    return queued


def cancel_idle_flush(conversation_id: str, user_id: str) -> None:
    cancel_job(MEMORY_FLUSH_JOB, user_id, conversation_id)


async def run_memory_flush_job(job: dict[str, Any]) -> dict[str, Any]:
    """Process pending messages for one conversation; errors let the worker retry."""
    conversation_id, user_id = job["conversation_id"], job["user_id"]
    if not background_cognition_enabled():
        return {"status": "disabled", "operation_count": 0}
    conversation = get_conversation(conversation_id, user_id)
    if conversation is None:
        return {"status": "conversation_unavailable", "operation_count": 0}
    messages = list(conversation.get("messages") or [])
    if not has_pending_background_cognition(conversation_id, user_id, messages):
        return {"status": "no_pending_messages", "operation_count": 0}

    cursor_before = _processed_through(conversation_id, user_id)
    result = await run_background_cognition(
        conversation_id, user_id, messages, conversation.get("agent_model")
    )
    if result.get("status") == "already_processing":
        schedule_job(MEMORY_FLUSH_JOB, user_id, conversation_id, delay_seconds=_BUSY_RETRY_SECONDS)
    elif _processed_through(conversation_id, user_id) == cursor_before:
        # Invalid output or a write error leaves the batch pending; the worker retries with backoff.
        raise RuntimeError(
            f"background cognition made no progress: {result.get('status')} "
            f"{'; '.join(result.get('errors') or [])}"[:400]
        )
    elif has_pending_background_cognition(conversation_id, user_id, messages):
        # One run handles one bounded batch; queue the next straight away.
        schedule_job(MEMORY_FLUSH_JOB, user_id, conversation_id, delay_seconds=0)
    logger.info(
        "agent.memory_flush conversation_id=%s status=%s", conversation_id, result.get("status")
    )
    return result


def _processed_through(conversation_id: str, user_id: str) -> int:
    state = get_processing_state(conversation_id, user_id)
    return state.processed_through_message_index if state else -1


__all__ = [
    "DEFAULT_IDLE_FLUSH_SECONDS",
    "MEMORY_FLUSH_JOB",
    "cancel_idle_flush",
    "catch_up_pending",
    "request_flush_now",
    "run_memory_flush_job",
    "schedule_idle_flush",
]
