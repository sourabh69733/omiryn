"""Schedules durable agent jobs; one pending row per kind and conversation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from agent.shared.clock import utc_now
from storage import cancel_agent_jobs, schedule_agent_job


def schedule_job(
    kind: str,
    user_id: str,
    conversation_id: str | None,
    *,
    delay_seconds: float = 0.0,
    payload: dict[str, Any] | None = None,
    key: str | None = None,
) -> None:
    """Run `kind` for this conversation after the delay; rescheduling replaces the time.

    One pending job per kind and conversation, unless `key` names what the job is about (a
    pair id, say), which allows one per kind, user and key.
    """
    now = utc_now()
    schedule_agent_job(
        kind=kind,
        dedupe_key=f"{kind}:{user_id}:{key or conversation_id}",
        user_id=user_id,
        conversation_id=conversation_id,
        run_after=now + timedelta(seconds=max(0.0, delay_seconds)),
        now=now,
        payload=payload,
    )


def cancel_job(kind: str, user_id: str, conversation_id: str) -> None:
    cancel_agent_jobs(user_id, conversation_id, kind)


__all__ = ["cancel_job", "schedule_job"]
