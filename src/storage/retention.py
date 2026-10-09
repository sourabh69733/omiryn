"""Deletes records we no longer need, on a schedule. The windows below are the retention policy.

Chats, memories, vibe lines and the profile stay until the user deletes them. What goes on its own:
debug records of how a reply or background run was built, finished background jobs, stale
temporary chats and, after a year, audit rows. Usage rows (tokens and cost, no text) stay for billing.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from agent.shared.clock import utc_now

from .agent_jobs import JOB_DONE, JOB_FAILED
from .conversations import TEMPORARY_CHAT_HOURS, delete_stale_temporary_conversations
from .database import ENGINE
from .debug_scrub import scrub_debug_records
from .schema import (
    agent_context_snapshots,
    agent_conversations,
    agent_jobs,
    agent_trace_steps,
    agent_traces,
    audit_events,
    data_point_extraction_debug,
    memory_batch_failures,
)

# Reply traces and context snapshots (counts and pointers only; the last few feed memory rotation).
DEBUG_DAYS = 30
# Background run records; free text in them is already scrubbed after 7 days.
BACKGROUND_DEBUG_DAYS = 90
# Finished or given-up background jobs, and batch failure notes.
JOB_DAYS = 30
AUDIT_DAYS = 365


def purge_expired_records() -> dict[str, int]:
    """Delete everything past its window; returns how many rows went from each place."""
    now = utc_now()
    debug_cutoff = now - timedelta(days=DEBUG_DAYS)
    job_cutoff = now - timedelta(days=JOB_DAYS)
    deleted: dict[str, int] = {}
    with ENGINE.begin() as connection:
        for name, table, cutoff, extra in (
            ("trace_steps", agent_trace_steps, debug_cutoff, ()),
            ("traces", agent_traces, debug_cutoff, ()),
            ("context_snapshots", agent_context_snapshots, debug_cutoff, ()),
            (
                "background_debug",
                data_point_extraction_debug,
                now - timedelta(days=BACKGROUND_DEBUG_DAYS),
                (),
            ),
            ("finished_jobs", agent_jobs, job_cutoff, (agent_jobs.c.status.in_([JOB_DONE, JOB_FAILED]),)),
            ("audit_events", audit_events, now - timedelta(days=AUDIT_DAYS), ()),
        ):
            deleted[name] = connection.execute(
                table.delete().where(table.c.created_at < cutoff, *extra)
            ).rowcount or 0
        deleted["batch_failures"] = connection.execute(
            memory_batch_failures.delete().where(memory_batch_failures.c.updated_at < job_cutoff)
        ).rowcount or 0
        stale_owners = connection.execute(
            select(agent_conversations.c.user_id)
            .where(
                agent_conversations.c.temporary.is_(True),
                agent_conversations.c.updated_at < now - timedelta(hours=TEMPORARY_CHAT_HOURS),
            )
            .distinct()
        ).scalars().all()
    deleted["temporary_chats"] = sum(delete_stale_temporary_conversations(owner) for owner in stale_owners)
    # What is left is inside its window; drop chat text from rows old enough to need none.
    deleted["scrubbed"] = sum(scrub_debug_records(apply=True).values())
    return deleted


__all__ = ["AUDIT_DAYS", "BACKGROUND_DEBUG_DAYS", "DEBUG_DAYS", "JOB_DAYS", "purge_expired_records"]
