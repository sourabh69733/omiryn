"""Verifies durable jobs and the idle memory flush built on them."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from agent.cognition.background.idle import (
    MEMORY_FLUSH_JOB,
    request_flush_now,
    run_memory_flush_job,
    schedule_idle_flush,
)
from agent.jobs.worker import JobWorker
from agent.memory_engine.processing.models import MemoryProcessingState
from agent.memory_engine.processing.service import save_processing_state
from agent.shared.clock import frozen_time
from storage import (
    JOB_DONE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    cancel_agent_jobs,
    claim_due_agent_jobs,
    delete_conversation,
    fail_agent_job,
    finish_agent_job,
    get_agent_job,
    reset_db,
    save_conversation,
    schedule_agent_job,
)

NOW = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
USER, CONVERSATION = "job-user", "job-conversation"
KEY = f"{MEMORY_FLUSH_JOB}:{USER}:{CONVERSATION}"


def _schedule(run_after: datetime, now: datetime = NOW, key: str = "k1") -> dict:
    return schedule_agent_job(
        kind="test",
        dedupe_key=key,
        user_id=USER,
        conversation_id=CONVERSATION,
        run_after=run_after,
        now=now,
    )


class AgentJobStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()

    def test_rescheduling_moves_one_row_instead_of_adding_rows(self) -> None:
        first = _schedule(NOW + timedelta(minutes=2))
        second = _schedule(NOW + timedelta(minutes=5))

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["run_after"], NOW + timedelta(minutes=5))
        self.assertEqual(second["status"], JOB_PENDING)

    def test_only_due_jobs_are_claimed_and_only_once(self) -> None:
        _schedule(NOW - timedelta(seconds=1), key="due")
        _schedule(NOW + timedelta(minutes=1), key="later")

        claimed = claim_due_agent_jobs(now=NOW, lease_seconds=60)
        self.assertEqual([job["dedupe_key"] for job in claimed], ["due"])
        self.assertEqual(claimed[0]["status"], JOB_RUNNING)
        self.assertEqual(claimed[0]["attempts"], 1)
        self.assertEqual(claim_due_agent_jobs(now=NOW, lease_seconds=60), [])

    def test_expired_lease_is_reclaimed_after_a_crash(self) -> None:
        _schedule(NOW)
        claim_due_agent_jobs(now=NOW, lease_seconds=60)

        self.assertEqual(claim_due_agent_jobs(now=NOW + timedelta(seconds=30), lease_seconds=60), [])
        reclaimed = claim_due_agent_jobs(now=NOW + timedelta(seconds=61), lease_seconds=60)
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(reclaimed[0]["attempts"], 2)

    def test_finish_marks_done_unless_rescheduled_while_running(self) -> None:
        _schedule(NOW)
        job = claim_due_agent_jobs(now=NOW, lease_seconds=60)[0]
        self.assertEqual(finish_agent_job(job, now=NOW), JOB_DONE)

        _schedule(NOW, key="busy")
        busy = claim_due_agent_jobs(now=NOW, lease_seconds=60)[0]
        _schedule(NOW + timedelta(minutes=2), key="busy")  # new message arrived mid-run
        self.assertEqual(finish_agent_job(busy, now=NOW), JOB_PENDING)
        self.assertEqual(get_agent_job("busy")["run_after"], NOW + timedelta(minutes=2))

    def test_failure_retries_or_gives_up_and_schedule_revives_it(self) -> None:
        _schedule(NOW)
        job = claim_due_agent_jobs(now=NOW, lease_seconds=60)[0]
        fail_agent_job(job, error="boom", retry_at=NOW + timedelta(minutes=1), now=NOW)
        retried = get_agent_job("k1")
        self.assertEqual((retried["status"], retried["last_error"]), (JOB_PENDING, "boom"))

        job = claim_due_agent_jobs(now=NOW + timedelta(minutes=1), lease_seconds=60)[0]
        fail_agent_job(job, error="boom", retry_at=None, now=NOW)
        self.assertEqual(get_agent_job("k1")["status"], JOB_FAILED)

        revived = _schedule(NOW + timedelta(minutes=5))
        self.assertEqual((revived["status"], revived["attempts"]), (JOB_PENDING, 0))

    def test_cancel_and_conversation_delete_remove_jobs(self) -> None:
        save_conversation({"id": CONVERSATION, "status": "active", "messages": []}, USER)
        _schedule(NOW, key="a")
        self.assertEqual(cancel_agent_jobs(USER, CONVERSATION, "test"), 1)
        self.assertIsNone(get_agent_job("a"))

        _schedule(NOW, key="b")
        delete_conversation(CONVERSATION, USER)
        self.assertIsNone(get_agent_job("b"))


class JobWorkerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()

    async def test_worker_runs_due_job_and_marks_it_done(self) -> None:
        handler = AsyncMock()
        _schedule(NOW)
        with frozen_time(NOW):
            ran = await JobWorker(handlers={"test": handler}).run_once()

        self.assertEqual(ran, 1)
        handler.assert_awaited_once()
        self.assertEqual(get_agent_job("k1")["status"], JOB_DONE)

    async def test_handler_errors_back_off_then_fail_after_three_attempts(self) -> None:
        worker = JobWorker(handlers={"test": AsyncMock(side_effect=RuntimeError("down"))})
        _schedule(NOW)
        clock = NOW
        for expected_delay in (60, 120):
            with frozen_time(clock):
                await worker.run_once()
            job = get_agent_job("k1")
            self.assertEqual(job["status"], JOB_PENDING)
            self.assertEqual(job["run_after"], clock + timedelta(seconds=expected_delay))
            clock = job["run_after"]
        with frozen_time(clock):
            await worker.run_once()
        self.assertEqual(get_agent_job("k1")["status"], JOB_FAILED)

    async def test_unknown_kind_fails_without_retry(self) -> None:
        _schedule(NOW)
        with frozen_time(NOW):
            await JobWorker(handlers={}).run_once()
        self.assertEqual(get_agent_job("k1")["status"], JOB_FAILED)


class MemoryFlushJobTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"})
        self.env.start()
        self.messages = [
            {"role": "user", "content": "I moved to Pune last month for a new job."},
            {"role": "assistant", "content": "Big change! How is it going?"},
        ]
        save_conversation(
            {"id": CONVERSATION, "status": "active", "messages": self.messages, "agent_model": "m"},
            USER,
        )
        self.job = {"conversation_id": CONVERSATION, "user_id": USER}

    def tearDown(self) -> None:
        self.env.stop()

    def _advance_cursor(self, *_args, **_kwargs) -> dict:
        save_processing_state(
            MemoryProcessingState(
                conversation_id=CONVERSATION, user_id=USER, processed_through_message_index=1
            )
        )
        return {"status": "live_applied"}

    def test_scheduling_debounces_and_flush_now_is_due_immediately(self) -> None:
        with frozen_time(NOW):
            schedule_idle_flush(CONVERSATION, USER)
        with frozen_time(NOW + timedelta(seconds=30)):
            schedule_idle_flush(CONVERSATION, USER)
        self.assertEqual(get_agent_job(KEY)["run_after"], NOW + timedelta(seconds=150))

        with frozen_time(NOW + timedelta(seconds=40)):
            request_flush_now(CONVERSATION, USER)
        self.assertEqual(get_agent_job(KEY)["run_after"], NOW + timedelta(seconds=40))

    async def test_pending_messages_are_processed(self) -> None:
        with patch(
            "agent.cognition.background.idle.run_background_cognition",
            new=AsyncMock(side_effect=self._advance_cursor),
        ) as run:
            result = await run_memory_flush_job(self.job)

        run.assert_awaited_once_with(CONVERSATION, USER, self.messages, "m")
        self.assertEqual(result["status"], "live_applied")

    async def test_nothing_pending_skips_the_model(self) -> None:
        self._advance_cursor()
        with patch(
            "agent.cognition.background.idle.run_background_cognition", new=AsyncMock()
        ) as run:
            result = await run_memory_flush_job(self.job)
        run.assert_not_awaited()
        self.assertEqual(result["status"], "no_pending_messages")

    async def test_run_without_progress_raises_so_the_worker_backs_off(self) -> None:
        with patch(
            "agent.cognition.background.idle.run_background_cognition",
            new=AsyncMock(return_value={"status": "live_invalid", "errors": ["bad json"]}),
        ):
            with self.assertRaisesRegex(RuntimeError, "no progress: live_invalid bad json"):
                await run_memory_flush_job(self.job)

    async def test_busy_batch_is_checked_again_later(self) -> None:
        with (
            frozen_time(NOW),
            patch(
                "agent.cognition.background.idle.run_background_cognition",
                new=AsyncMock(return_value={"status": "already_processing"}),
            ),
        ):
            await run_memory_flush_job(self.job)
        self.assertEqual(get_agent_job(KEY)["run_after"], NOW + timedelta(seconds=60))


if __name__ == "__main__":
    unittest.main()
