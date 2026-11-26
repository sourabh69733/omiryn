"""The pick as a background job: the operator's request queues it and returns at once.

A pool of forty ready people is 780 judge calls. Inside one web request that times out long
before it ends, and whatever was judged by then was lost to the operator. Here the request
writes a run row and queues one durable job. The job judges in passes (agent.matching.pick):
a pass runs for about a minute, stores every judgement as it comes, and queues itself again
while pairs are left, so other jobs (asks, reminders, memory) get their turn between passes and
a restart picks up where the last judgement was stored. The last pass makes the proposal and
writes it on the run, which the operator's page reads.

What the run row holds is ids, counts and states. The judge's words stay on the pairs.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent.shared.clock import utc_now

logger = logging.getLogger(__name__)

MATCH_PICK_JOB = "match_pick"
# How long one pass keeps starting judge calls. Short, so the one worker loop is not held for
# long; a call already started may run past it (the judge call's own limit is 45 s).
PASS_SECONDS = 60.0
# Judge calls in flight at once inside a pass.
PARALLEL_JUDGES = 4
# A pair whose judge call failed this many times in one run is left out of it, and named in the proposal.
MAX_PAIR_FAILURES = 2
# After a pass with failed calls the next one waits this long: a provider in trouble gets a moment.
RETRY_AFTER_FAILURE_SECONDS = 30.0
# The job tells storage it is alive this often; the worker's lease is five minutes.
_ALIVE_EVERY_SECONDS = 60.0
_LEASE_SECONDS = 300.0


def start_pick(pool_id: str, *, created_by: str | None = None) -> dict[str, Any]:
    """Queue the pick for a pool and return its run. While a run for the pool is going, that run
    is returned and nothing new starts."""
    from agent.jobs.queue import schedule_job
    from storage import start_match_pick_run

    run, created = start_match_pick_run(pool_id, created_by=created_by)
    # Queued again even for a run already going: harmless when its job is alive (one job per pool),
    # and it restarts a run whose job was lost.
    schedule_job(MATCH_PICK_JOB, created_by or "operator", None, payload={"pool_id": pool_id, "run_id": run["id"]}, key=pool_id)
    logger.info("agent.matching.pick_job.queued pool_id=%s run_id=%s new=%s", pool_id, run["id"], created)
    return run


async def run_match_pick_job(job: dict[str, Any]) -> bool:
    """One pass. True when the pass did its work (the pick may still have passes to go)."""
    from agent.jobs.queue import schedule_job
    from agent.jobs.worker import MAX_ATTEMPTS
    from storage import PICK_RUN_OPEN, get_match_pick_run, record_audit_event, update_match_pick_run

    from .pick import pick_pool_pass

    payload = dict(job.get("payload") or {})
    run = get_match_pick_run(str(payload.get("run_id") or ""))
    if run is None or run["status"] not in PICK_RUN_OPEN:
        return False
    progress = {"passes": 0, "judged": 0, "left": None, "failures": {}, "notes_tried": [], **(run.get("progress") or {})}
    failures: dict[str, int] = dict(progress.get("failures") or {})
    update_match_pick_run(run["id"], status="running")
    alive = asyncio.create_task(_keep_alive(str(job.get("id") or ""), run["id"]))
    try:
        done = await pick_pool_pass(
            run["pool_id"],
            created_by=run.get("created_by"),
            seconds=PASS_SECONDS,
            parallel=PARALLEL_JUDGES,
            gave_up={key for key, count in failures.items() if count >= MAX_PAIR_FAILURES},
            notes_tried=set(progress.get("notes_tried") or []),
        )
    except Exception as error:
        # The worker tries a failed job again, a few times. After the last try the run must not
        # stay "running" for ever: the operator has to see that it failed.
        if int(job.get("attempts") or 0) >= MAX_ATTEMPTS:
            update_match_pick_run(run["id"], status="failed", error=type(error).__name__)
            logger.warning("agent.matching.pick_job.failed pool_id=%s run_id=%s error_type=%s", run["pool_id"], run["id"], type(error).__name__)
        raise
    finally:
        alive.cancel()
    for key in done.failed:
        failures[key] = failures.get(key, 0) + 1
    progress.update(
        passes=int(progress.get("passes") or 0) + 1,
        judged=int(progress.get("judged") or 0) + done.judged,
        left=done.left,
        failures=failures,
        notes_tried=sorted({*(progress.get("notes_tried") or []), *done.notes_tried}),
    )
    if done.proposal is None:
        update_match_pick_run(run["id"], progress=progress)
        schedule_job(
            MATCH_PICK_JOB, str(job["user_id"]), None, delay_seconds=RETRY_AFTER_FAILURE_SECONDS if done.failed else 0.0, payload=payload, key=run["pool_id"]
        )
        return True
    proposal = done.proposal
    proposal.judged = progress["judged"]
    update_match_pick_run(run["id"], status="done", progress=progress, result=proposal.as_record())
    record_audit_event(
        "match.pick_done", actor_id=None, actor_role="system", target_id=run["pool_id"],
        detail={"run_id": run["id"], "passes": progress["passes"], "judged": progress["judged"], "pairs": len(proposal.pairs), "waiting": len(proposal.waiting), "not_judged": len(proposal.not_judged)},
    )
    logger.info("agent.matching.pick_job.done pool_id=%s run_id=%s passes=%s judged=%s pairs=%s", run["pool_id"], run["id"], progress["passes"], progress["judged"], len(proposal.pairs))
    return True


async def _keep_alive(job_id: str, run_id: str) -> None:
    """While a pass runs: keep the job's lease out in front, so a second worker does not take a
    long pass for dead and run the pick twice, and keep the run row fresh, so it is not taken for stalled."""
    from storage import extend_agent_job_lease, update_match_pick_run

    while True:
        await asyncio.sleep(_ALIVE_EVERY_SECONDS)
        try:
            if job_id:
                extend_agent_job_lease(job_id, now=utc_now(), lease_seconds=_LEASE_SECONDS)
            update_match_pick_run(run_id)
        except Exception as error:  # a missed beat must not end the pass
            logger.warning("agent.matching.pick_job.alive_failed error_type=%s", type(error).__name__)


__all__ = ["MATCH_PICK_JOB", "MAX_PAIR_FAILURES", "PARALLEL_JUDGES", "PASS_SECONDS", "run_match_pick_job", "start_pick"]
