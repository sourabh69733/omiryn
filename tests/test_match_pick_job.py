"""The pick as a background job: the operator's request queues it and returns at once; the job
judges in passes that each store what they judged, so the next pass (or a restart) goes on from
there; a pair whose judge call keeps failing is left out and named; a run that crashes for good
says failed; one run per pool at a time."""

import os
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.jobs.worker import MAX_ATTEMPTS, JobWorker
from agent.matching.compatibility import MatchCheck
from agent.matching.pick import pick_pool_pass
from agent.matching.pick_job import MATCH_PICK_JOB, run_match_pick_job, start_pick
from agent.shared.clock import utc_now
from api.main import app
from storage import (
    claim_due_agent_jobs, create_match_pool, extend_agent_job_lease, get_agent_job, get_match_pick_run, join_match_pool, latest_match_pick_run, list_match_pairs,
    reset_db, save_user_profile, start_match_pick_run, update_vibe_card,
)
from storage.user_deletion import delete_user_private_data
from test_matching import ready_areas

PEOPLE = (("ua", "Aman"), ("ub", "Bela"), ("uc", "Chitra"), ("ud", "Dev"))


def _all_ready():
    return patch("agent.matching.readiness.match_readiness", side_effect=lambda u: type("R", (), {"ready": True, "facts_known": {}})())


def _check(a: str, b: str) -> MatchCheck:
    fit = "yes" if {a, b} in ({"ua", "ub"}, {"uc", "ud"}) else "maybe"
    return MatchCheck(fit, 50, ("humor",), [{"source": "area:humor", "area": "humor", "text": "Both like dry humour."}] if fit == "yes" else [], chemistry="Easy talk.")


class PickJobTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AUTH_REQUIRED": "false", "ADMIN_ALLOW_UNAUTHENTICATED_DEV": "true", "AGENT_PROVIDER": "mock"})
        self.env.start()
        self.pool = create_match_pool("Baner block A")
        for user_id, name in PEOPLE:
            save_user_profile(user_id, "female", "male", display_name=name, city="Pune")
            update_vibe_card(user_id, ready_areas())
            join_match_pool(user_id, self.pool["join_code"])
        self.job_key = f"{MATCH_PICK_JOB}:op:{self.pool['id']}"

    def tearDown(self) -> None:
        self.env.stop()

    async def test_the_request_returns_at_once_and_the_job_does_the_pick(self) -> None:
        judge = AsyncMock(side_effect=lambda a, b, **_: _check(a, b))
        client = TestClient(app)
        address = f"/api/admin/pools/{self.pool['id']}/pick"
        with _all_ready(), patch("agent.matching.compatibility.check_compatibility", judge):
            self.assertEqual(client.post("/api/admin/pools/nope/pick").status_code, 404)
            self.assertEqual(client.get("/api/admin/pools/nope/pick").status_code, 404)
            self.assertIsNone(client.get(address).json()["run"])  # never picked
            response = client.post(address)
            self.assertEqual(response.status_code, 202)
            run = response.json()["run"]
            self.assertEqual((run["status"], run["proposal"]), ("queued", None))
            judge.assert_not_awaited()  # nothing was judged inside the request
            self.assertEqual(list_match_pairs(self.pool["id"]), [])
            # Asking again while it is going gives the same run, not a second pick.
            self.assertEqual(client.post(address).json()["run"]["id"], run["id"])
            self.assertEqual(client.get(address).json()["run"]["status"], "queued")

            self.assertEqual(await JobWorker().run_once(), 1)
            done = client.get(address).json()["run"]
        self.assertEqual(judge.await_count, 6)
        self.assertEqual((done["id"], done["status"], done["error"]), (run["id"], "done", None))
        self.assertEqual(done["progress"], {"passes": 1, "judged": 6, "left": 0, "failed_calls": 0})
        proposal = done["proposal"]
        self.assertEqual(sorted(frozenset((p["user_a"], p["user_b"])) for p in proposal["pairs"]), sorted([frozenset({"ua", "ub"}), frozenset({"uc", "ud"})]))
        self.assertEqual((proposal["judged"], proposal["waiting"], proposal["not_judged"]), (6, [], []))
        # What the operator may read of a picked pair comes from the stored pair, cut as everywhere else.
        self.assertEqual({(p["status"], p["fit"], p["reasons"][0]["text"], p["chemistry"]) for p in proposal["pairs"]}, {("proposed", "yes", "Both like dry humour.", "Easy talk.")})
        self.assertEqual(sorted(pair["status"] for pair in list_match_pairs(self.pool["id"])), ["candidate"] * 4 + ["proposed"] * 2)
        # The run row itself keeps ids and counts, never what the judge wrote.
        stored = get_match_pick_run(run["id"])
        self.assertNotIn("dry humour", str(stored))
        self.assertNotIn("Easy talk", str(stored))
        self.assertEqual(sorted(stored["result"]["pairs"][0]), ["gaps", "pair_id", "user_a", "user_b"])
        # A new request after it finished starts a new run.
        self.assertNotEqual(start_pick(self.pool["id"], created_by="op")["id"], run["id"])

    async def test_a_pass_stops_on_time_and_the_next_goes_on_from_what_is_stored(self) -> None:
        clock = [1000.0]

        async def slow_judge(a, b, **_):
            clock[0] += 30.0  # every judge call takes half a minute
            return _check(a, b)

        judge = AsyncMock(side_effect=slow_judge)
        run = start_pick(self.pool["id"], created_by="op")
        with _all_ready(), patch("agent.matching.compatibility.check_compatibility", judge), patch("agent.matching.pick.time.monotonic", lambda: clock[0]), \
                patch("agent.matching.pick_job.PARALLEL_JUDGES", 1):
            self.assertEqual(await JobWorker().run_once(), 1)
            after_one = get_match_pick_run(run["id"])
            # A minute a pass: two calls fit. Both are stored; the job has queued itself for the rest.
            self.assertEqual((after_one["status"], after_one["progress"]["judged"], after_one["progress"]["left"], after_one["result"]), ("running", 2, 4, None))
            self.assertEqual([pair["status"] for pair in list_match_pairs(self.pool["id"])], ["candidate", "candidate"])
            self.assertEqual(get_agent_job(self.job_key)["status"], "pending")
            self.assertEqual(await JobWorker().run_once(), 1)
            self.assertEqual(get_match_pick_run(run["id"])["progress"]["judged"], 4)
            self.assertEqual(await JobWorker().run_once(), 1)
            self.assertEqual(await JobWorker().run_once(), 0)  # finished: nothing queued any more
        done = get_match_pick_run(run["id"])
        self.assertEqual((done["status"], done["progress"]["passes"], done["progress"]["judged"], done["progress"]["left"]), ("done", 3, 6, 0))
        self.assertEqual(judge.await_count, 6)  # no pair was judged twice
        self.assertEqual(len(done["result"]["pairs"]), 2)
        self.assertEqual(get_agent_job(self.job_key)["status"], "done")

    async def test_a_pair_whose_judge_call_keeps_failing_is_left_out_and_named(self) -> None:
        async def flaky(a, b, **_):
            if {a, b} == {"ua", "ub"}:
                raise TimeoutError("judge timed out")
            return _check(a, b)

        run = start_pick(self.pool["id"], created_by="op")
        with _all_ready(), patch("agent.matching.compatibility.check_compatibility", AsyncMock(side_effect=flaky)), patch("agent.matching.pick_job.RETRY_AFTER_FAILURE_SECONDS", 0.0):
            await JobWorker().run_once()
            first = get_match_pick_run(run["id"])
            self.assertEqual((first["status"], first["progress"]["judged"], first["progress"]["left"], first["progress"]["failures"]), ("running", 5, 1, {"ua|ub": 1}))
            await JobWorker().run_once()  # tried once more
            self.assertEqual(get_match_pick_run(run["id"])["status"], "running")
            await JobWorker().run_once()  # given up on: the pick goes ahead without that pair
        done = get_match_pick_run(run["id"])
        self.assertEqual((done["status"], done["progress"]["judged"], done["progress"]["passes"]), ("done", 5, 3))
        self.assertEqual(done["result"]["not_judged"], [{"user_a": "ua", "user_b": "ub", "why": "the judge call kept failing"}])
        self.assertEqual(sorted(frozenset((p["user_a"], p["user_b"])) for p in done["result"]["pairs"]), [frozenset({"uc", "ud"})])
        # In one go, as before, the failure reaches the caller.
        other = create_match_pool("Other block")
        for user_id, _ in PEOPLE:
            join_match_pool(user_id, other["join_code"])
        with _all_ready(), patch("agent.matching.compatibility.check_compatibility", AsyncMock(side_effect=flaky)), self.assertRaises(TimeoutError):
            await pick_pool_pass(other["id"])

    async def test_a_run_that_crashes_for_good_says_failed(self) -> None:
        run = start_pick(self.pool["id"], created_by="op")
        job = {"id": "j", "kind": MATCH_PICK_JOB, "user_id": "op", "conversation_id": None, "payload": {"pool_id": self.pool["id"], "run_id": run["id"]}, "attempts": 1}
        with patch("agent.matching.pick.pick_pool_pass", AsyncMock(side_effect=RuntimeError("database went away"))):
            with self.assertRaises(RuntimeError):
                await run_match_pick_job(job)
            self.assertEqual(get_match_pick_run(run["id"])["status"], "running")  # the worker will try again
            with self.assertRaises(RuntimeError):
                await run_match_pick_job({**job, "attempts": MAX_ATTEMPTS})
        failed = get_match_pick_run(run["id"])
        self.assertEqual((failed["status"], failed["error"]), ("failed", "RuntimeError"))
        self.assertIsNotNone(failed["finished_at"])
        self.assertNotIn("database went away", str(failed))
        self.assertFalse(await run_match_pick_job(job))  # a closed run is not picked up again
        self.assertEqual(TestClient(app).get(f"/api/admin/pools/{self.pool['id']}/pick").json()["run"]["status"], "failed")

    def test_one_run_at_a_time_and_a_stalled_one_is_replaced(self) -> None:
        now = utc_now()
        first, created = start_match_pick_run(self.pool["id"], created_by="op", now=now)
        again, created_again = start_match_pick_run(self.pool["id"], created_by="op", now=now + timedelta(minutes=5))
        self.assertEqual((created, created_again, again["id"]), (True, False, first["id"]))
        # Nobody has touched it for over half an hour: its worker is gone.
        fresh, created_fresh = start_match_pick_run(self.pool["id"], created_by="op", now=now + timedelta(minutes=45))
        self.assertTrue(created_fresh)
        self.assertNotEqual(fresh["id"], first["id"])
        self.assertEqual((get_match_pick_run(first["id"])["status"], get_match_pick_run(first["id"])["error"]), ("failed", "stalled"))
        self.assertEqual(latest_match_pick_run(self.pool["id"])["id"], fresh["id"])

    def test_a_long_job_can_keep_its_lease(self) -> None:
        start_pick(self.pool["id"], created_by="op")
        now = utc_now()
        job = claim_due_agent_jobs(now=now, lease_seconds=300)[0]
        self.assertTrue(extend_agent_job_lease(job["id"], now=now + timedelta(seconds=240), lease_seconds=300))
        # Past the first lease, the job is still held: a second worker does not take it.
        self.assertEqual(claim_due_agent_jobs(now=now + timedelta(seconds=400), lease_seconds=300), [])
        self.assertEqual(len(claim_due_agent_jobs(now=now + timedelta(seconds=600), lease_seconds=300)), 1)
        self.assertFalse(extend_agent_job_lease("no-such-job", now=now, lease_seconds=300))

    async def test_deleting_an_account_drops_the_finished_runs_that_list_it(self) -> None:
        run = start_pick(self.pool["id"], created_by="op")
        with _all_ready(), patch("agent.matching.compatibility.check_compatibility", AsyncMock(side_effect=lambda a, b, **_: _check(a, b))):
            await JobWorker().run_once()
        self.assertIn("ua", str(get_match_pick_run(run["id"])["result"]))
        delete_user_private_data("ua")
        self.assertIsNone(get_match_pick_run(run["id"]))


if __name__ == "__main__":
    unittest.main()
