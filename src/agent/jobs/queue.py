"""Schedules durable agent jobs; one pending row per kind and conversation."""

from __future__ import annotations

from datetime import timedelta

from agent.shared.clock import utc_now
from storage import cancel_agent_jobs, schedule_agent_job


def schedule_job(
    kind: str,
    user_id: str,
    conversation_id: str,
    *,
    delay_seconds: float = 0.0,
) -> None:
    """Run `kind` for this conversation after the delay; rescheduling replaces the time."""
    now = utc_now()
    schedule_agent_job(
        kind=kind,
        dedupe_key=f"{kind}:{user_id}:{conversation_id}",
        user_id=user_id,
        conversation_id=conversation_id,
        run_after=now + timedelta(seconds=max(0.0, delay_seconds)),
        now=now,
    )


def cancel_job(kind: str, user_id: str, conversation_id: str) -> None:
    cancel_agent_jobs(user_id, conversation_id, kind)


__all__ = ["cancel_job", "schedule_job"]
