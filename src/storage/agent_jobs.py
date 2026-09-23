"""Persists durable background jobs so scheduled work survives restarts.

All times are stored in UTC. Callers pass `now`, so storage never reads the clock itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select

from .database import ENGINE
from .schema import agent_jobs
from .utils import _require_user_id

JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"


def schedule_agent_job(
    *,
    kind: str,
    dedupe_key: str,
    user_id: str,
    conversation_id: str | None,
    run_after: datetime,
    now: datetime,
) -> dict[str, Any]:
    """Create the job, or move its run_after if one with this key already exists.

    A finished job is reset to pending with fresh attempts. A running job keeps running;
    `finish_agent_job` notices the new run_after and leaves it pending for another pass.
    """
    owner_id = _require_user_id(user_id, "agent job")
    run_after_utc, now_utc = _utc(run_after), _utc(now)
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(agent_jobs).where(agent_jobs.c.dedupe_key == dedupe_key)
        ).mappings().first()
        if existing is None:
            job_id = str(uuid4())
            connection.execute(
                agent_jobs.insert().values(
                    id=job_id,
                    kind=kind,
                    dedupe_key=dedupe_key,
                    user_id=owner_id,
                    conversation_id=conversation_id,
                    status=JOB_PENDING,
                    run_after=run_after_utc,
                    attempts=0,
                    created_at=now_utc,
                    updated_at=now_utc,
                )
            )
        else:
            job_id = existing["id"]
            values: dict[str, Any] = {"run_after": run_after_utc, "updated_at": now_utc}
            if existing["status"] in {JOB_DONE, JOB_FAILED}:
                values.update(status=JOB_PENDING, attempts=0, last_error=None)
            connection.execute(agent_jobs.update().where(agent_jobs.c.id == job_id).values(**values))
        row = connection.execute(select(agent_jobs).where(agent_jobs.c.id == job_id)).mappings().one()
    return _job_from_row(row)


def claim_due_agent_jobs(
    *,
    now: datetime,
    lease_seconds: float,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Atomically claim due pending jobs, and running jobs whose worker lease expired."""
    now_utc = _utc(now)
    due = or_(
        and_(agent_jobs.c.status == JOB_PENDING, agent_jobs.c.run_after <= now_utc),
        and_(agent_jobs.c.status == JOB_RUNNING, agent_jobs.c.locked_until <= now_utc),
    )
    claimed: list[dict[str, Any]] = []
    with ENGINE.begin() as connection:
        candidates = connection.execute(
            select(agent_jobs).where(due).order_by(agent_jobs.c.run_after.asc()).limit(limit)
        ).mappings().all()
        for candidate in candidates:
            # The same due condition in the UPDATE makes this a compare-and-set across workers.
            result = connection.execute(
                agent_jobs.update()
                .where(agent_jobs.c.id == candidate["id"], due)
                .values(
                    status=JOB_RUNNING,
                    locked_until=now_utc + timedelta(seconds=lease_seconds),
                    attempts=agent_jobs.c.attempts + 1,
                    updated_at=now_utc,
                )
            )
            if result.rowcount == 1:
                row = connection.execute(
                    select(agent_jobs).where(agent_jobs.c.id == candidate["id"])
                ).mappings().one()
                claimed.append(_job_from_row(row))
    return claimed


def finish_agent_job(job: dict[str, Any], *, now: datetime) -> str:
    """Mark a claimed job done, unless it was rescheduled while running."""
    now_utc = _utc(now)
    with ENGINE.begin() as connection:
        result = connection.execute(
            agent_jobs.update()
            .where(
                agent_jobs.c.id == job["id"],
                agent_jobs.c.run_after == _utc(job["run_after"]),
            )
            .values(status=JOB_DONE, locked_until=None, last_error=None, updated_at=now_utc)
        )
        if result.rowcount == 1:
            return JOB_DONE
        connection.execute(
            agent_jobs.update()
            .where(agent_jobs.c.id == job["id"])
            .values(status=JOB_PENDING, locked_until=None, attempts=0, updated_at=now_utc)
        )
    return JOB_PENDING


def fail_agent_job(
    job: dict[str, Any],
    *,
    error: str,
    retry_at: datetime | None,
    now: datetime,
) -> str:
    """Record a failure and either schedule a retry or give up."""
    status = JOB_PENDING if retry_at is not None else JOB_FAILED
    values: dict[str, Any] = {
        "status": status,
        "locked_until": None,
        "last_error": error[:500],
        "updated_at": _utc(now),
    }
    if retry_at is not None:
        values["run_after"] = _utc(retry_at)
    with ENGINE.begin() as connection:
        connection.execute(agent_jobs.update().where(agent_jobs.c.id == job["id"]).values(**values))
    return status


def cancel_agent_jobs(user_id: str, conversation_id: str, kind: str | None = None) -> int:
    """Delete jobs that are not running for one conversation."""
    owner_id = _require_user_id(user_id, "agent job")
    conditions = [
        agent_jobs.c.user_id == owner_id,
        agent_jobs.c.conversation_id == conversation_id,
        agent_jobs.c.status != JOB_RUNNING,
    ]
    if kind is not None:
        conditions.append(agent_jobs.c.kind == kind)
    with ENGINE.begin() as connection:
        return int(connection.execute(agent_jobs.delete().where(*conditions)).rowcount or 0)


def get_agent_job(dedupe_key: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(agent_jobs).where(agent_jobs.c.dedupe_key == dedupe_key)
        ).mappings().first()
    return _job_from_row(row) if row else None


def _utc(value: datetime) -> datetime:
    """Store naive-UTC-compatible values; SQLite drops offsets, so everything stays in UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "dedupe_key": row["dedupe_key"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "status": row["status"],
        "run_after": _utc(row["run_after"]),
        "locked_until": _utc(row["locked_until"]) if row["locked_until"] else None,
        "attempts": int(row["attempts"] or 0),
        "last_error": row["last_error"],
    }


__all__ = [
    "JOB_DONE",
    "JOB_FAILED",
    "JOB_PENDING",
    "JOB_RUNNING",
    "cancel_agent_jobs",
    "claim_due_agent_jobs",
    "fail_agent_job",
    "finish_agent_job",
    "get_agent_job",
    "schedule_agent_job",
]
