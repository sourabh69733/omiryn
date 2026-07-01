import unittest

from fastapi.testclient import TestClient

from agent.evals.runner import run_agent_evals
from api.main import app
from storage import list_agent_eval_case_results, list_agent_eval_runs


class AgentEvalRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_agent_evals_pass_with_mock_provider(self) -> None:
        report = await run_agent_evals()

        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["passed"], report["total"])
        self.assertGreaterEqual(report["total"], 2)
        first_result = report["results"][0]
        self.assertTrue(first_result["passed"])
        self.assertIn("context_pack", first_result["observed_trace_steps"])
        self.assertTrue(first_result["observed_facts"])

        runs = list_agent_eval_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["id"], report["run_id"])
        self.assertEqual(runs[0]["status"], "passed")
        self.assertEqual(runs[0]["passed"], report["passed"])

        case_results = list_agent_eval_case_results(report["run_id"])
        self.assertEqual(len(case_results), report["total"])
        self.assertTrue(all(result["status"] == "passed" for result in case_results))
        self.assertTrue(case_results[0]["expected"]["facts"])
        self.assertIn("trace_steps", case_results[0]["observed"])

    async def test_admin_eval_endpoint_returns_persisted_runs(self) -> None:
        report = await run_agent_evals()
        client = TestClient(app)

        response = client.get("/api/admin/evals")
        overview_response = client.get("/api/admin/overview")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["total"], 1)
        self.assertEqual(data["summary"]["case_failures"], 0)
        self.assertEqual(data["runs"][0]["id"], report["run_id"])
        self.assertEqual(len(data["runs"][0]["cases"]), report["total"])

        self.assertEqual(overview_response.status_code, 200)
        self.assertEqual(overview_response.json()["summary"]["agent_eval_run_count"], 1)


if __name__ == "__main__":
    unittest.main()
