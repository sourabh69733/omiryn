import unittest

from agent.evals.runner import run_agent_evals
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


if __name__ == "__main__":
    unittest.main()
