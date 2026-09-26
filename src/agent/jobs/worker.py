"""Runs due durable jobs on an interval inside the API process.

Jobs live in the database, so a restart loses nothing: the next worker pass (also run
at startup) picks up whatever was due. Claims are atomic, so several instances can poll
the same table without running a job twice.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from agent.shared.clock import utc_now
from storage import claim_due_agent_jobs, fail_agent_job, finish_agent_job

logger = logging.getLogger(__name__)

JobHandler = Callable[[dict[str, Any]], Awaitable[Any]]

DEFAULT_POLL_SECONDS = 10.0
# Longer than the background cognition timeout (120s) plus embedding and storage work.
DEFAULT_LEASE_SECONDS = 300.0
MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 60.0


def _job_handlers() -> dict[str, JobHandler]:
    # Imported here so storage and the worker load without pulling in cognition code.
    from agent.cognition.background.idle import MEMORY_FLUSH_JOB, run_memory_flush_job
    from agent.proactive.story import run_story_part_job
    from agent.runtime.story_mode import STORY_PART_JOB

    return {MEMORY_FLUSH_JOB: run_memory_flush_job, STORY_PART_JOB: run_story_part_job}


def jobs_enabled() -> bool:
    return os.getenv("AGENT_JOBS_ENABLED", "true").strip().lower() not in {"0", "false", "off"}


class JobWorker:
    def __init__(
        self,
        *,
        poll_seconds: float | None = None,
        lease_seconds: float | None = None,
        handlers: dict[str, JobHandler] | None = None,
    ) -> None:
        self._poll = poll_seconds or float(
            os.getenv("AGENT_JOB_POLL_SECONDS", DEFAULT_POLL_SECONDS)
        )
        self._lease = lease_seconds or DEFAULT_LEASE_SECONDS
        self._handlers = handlers
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None and jobs_enabled():
            self._task = asyncio.create_task(self._loop(), name="agent-jobs")

    async def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def run_once(self) -> int:
        """Claim and run every due job once; returns how many were claimed."""
        jobs = claim_due_agent_jobs(now=utc_now(), lease_seconds=self._lease)
        for job in jobs:
            await self._run(job)
        return len(jobs)

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("agent.jobs.pass_failed")
            await asyncio.sleep(self._poll)

    async def _run(self, job: dict[str, Any]) -> None:
        handler = (self._handlers or _job_handlers()).get(job["kind"])
        if handler is None:
            fail_agent_job(job, error="unknown job kind", retry_at=None, now=utc_now())
            return
        try:
            await handler(job)
        except Exception as error:
            logger.exception("agent.jobs.failed kind=%s id=%s", job["kind"], job["id"])
            retry_at = (
                utc_now() + timedelta(seconds=RETRY_BASE_SECONDS * 2 ** (job["attempts"] - 1))
                if job["attempts"] < MAX_ATTEMPTS
                else None
            )
            fail_agent_job(
                job,
                error=f"{type(error).__name__}: {error}",
                retry_at=retry_at,
                now=utc_now(),
            )
            return
        finish_agent_job(job, now=utc_now())


job_worker = JobWorker()


__all__ = ["JobWorker", "job_worker", "jobs_enabled"]
