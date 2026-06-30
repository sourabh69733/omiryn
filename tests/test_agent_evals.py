import unittest

from agent.evals.runner import run_agent_evals


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


if __name__ == "__main__":
    unittest.main()
