"""A rewrite asked for by a check reads what the draft looked up, so it never answers from memory."""

import unittest
from unittest.mock import patch

from agent.runtime.steps.checks import freshen_reply
from agent.runtime.steps.draft import write_draft
from agent.providers.gateway.clients import TOOL_CALL_MARKER
from agent.runtime.steps.job import ReplyJob
from agent.tools import ToolResult

FOUND = "TCS Ninja 3.36 LPA, Digital 7 LPA, Prime 9 LPA (source: example.com, Nov 2026)"


class RewriteSeesLookupTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_rewrite_gets_the_search_results(self) -> None:
        seen: list[list[dict]] = []
        replies = iter([
            TOOL_CALL_MARKER + '{"calls": [{"name": "web_search", "arguments": {"query": "TCS fresher salary 2026"}}]}',
            "Ninja 3.36 LPA hai. Tum kis role ke liye dekh rahe ho? Offer aaya hai? Kab join karna hai?",
            "Ninja 3.36 LPA, Digital 7 LPA. Kis role ke liye dekh rahe ho?",
        ])

        async def generate(messages, **kwargs):
            seen.append(list(messages))
            return next(replies)

        async def run_calls(calls, context):
            return [ToolResult(FOUND, {"tool": call.name}) for call in calls]

        job = ReplyJob([{"role": "user", "content": "tcs fresher salary kitni hoti hai"}], {}, generate, question_limit=1)
        with patch("agent.tools.loop.run_calls", run_calls):
            draft = await write_draft(job)
            rewritten, info = await freshen_reply(draft.reply, job)

        self.assertTrue(info["rewritten"])
        self.assertEqual(rewritten, "Ninja 3.36 LPA, Digital 7 LPA. Kis role ke liye dekh rahe ho?")
        rewrite_call = seen[-1]
        self.assertEqual([message["role"] for message in rewrite_call], ["user", "assistant", "tool", "system"])
        self.assertEqual(rewrite_call[2]["content"], FOUND)
        self.assertIn("Rewrite needed", rewrite_call[-1]["content"])

    async def test_a_turn_with_no_lookup_is_unchanged(self) -> None:
        seen: list[list[dict]] = []

        async def generate(messages, **kwargs):
            seen.append(list(messages))
            return "theek hai, bolo."

        job = ReplyJob([{"role": "user", "content": "hi"}], {}, generate)
        await job.rewrite("Rewrite needed: say less.")
        self.assertEqual([message["role"] for message in seen[-1]], ["user", "system"])


if __name__ == "__main__":
    unittest.main()
