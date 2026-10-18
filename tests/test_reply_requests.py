"""The reply check against how the user asked to be talked to."""

import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.conversation_engine.policy.requests import broken_requests, how_to_talk_requests
from agent.runtime.orchestrator import _follow_requests

SOURCES = [
    {"source_type": "user_card", "content": "- Lives in Pune"},
    {
        "source_type": "how_to_talk",
        "content": "How the user asked you to talk to them, in earlier chats. Follow it unless they change it.\n"
        "- Wants no questions from the companion.\n- Prefers short replies.",
    },
]
REQUESTS = ["Wants no questions from the companion.", "Prefers short replies."]
ARGS = {"conversation_id": "c"}


class RequestHelpersTest(unittest.TestCase):
    def test_requests_come_from_the_how_to_talk_source_only(self) -> None:
        self.assertEqual(how_to_talk_requests(SOURCES), REQUESTS)

    def test_only_given_requests_count_as_broken(self) -> None:
        raw = {"broken": ["Prefers short replies.", "Something the checker made up", "Prefers short replies."]}
        self.assertEqual(broken_requests(raw, REQUESTS), ["Prefers short replies."])
        self.assertEqual(broken_requests("not json", REQUESTS), [])


class FollowRequestsTest(unittest.IsolatedAsyncioTestCase):
    async def _follow(self, check: object, rewrite: str = "Venus ka din uske saal se lamba hota hai.", requests=REQUESTS):
        checker = AsyncMock(side_effect=check) if isinstance(check, Exception) else AsyncMock(return_value=check)
        writer = AsyncMock(return_value=rewrite)
        with patch("agent.runtime.orchestrator.check_reply_requests", checker), patch(
            "agent.runtime.orchestrator.generate_agent_reply", writer
        ):
            result = await _follow_requests(
                "Space is cool! Kya tumhe stars pasand hain?",
                requests=requests,
                reply_messages=[{"role": "user", "content": "space ke baare mein batao"}],
                generation_arguments=ARGS,
            )
        return result, checker, writer

    async def test_no_requests_no_check(self) -> None:
        (reply, info), checker, _ = await self._follow({"broken": []}, requests=[])
        self.assertIsNone(info)
        checker.assert_not_called()

    async def test_kept_requests_keep_the_draft(self) -> None:
        (reply, info), _, writer = await self._follow({"broken": []})
        self.assertEqual(reply, "Space is cool! Kya tumhe stars pasand hain?")
        writer.assert_not_called()

    async def test_a_broken_request_gets_one_rewrite_told_what_was_broken(self) -> None:
        (reply, info), _, writer = await self._follow({"broken": ["Wants no questions from the companion."]})
        self.assertEqual(reply, "Venus ka din uske saal se lamba hota hai.")
        self.assertTrue(info["rewritten"])
        note = writer.await_args.args[0][-1]
        self.assertEqual(note["role"], "system")
        self.assertIn("Wants no questions from the companion.", note["content"])

    async def test_a_failed_check_keeps_the_draft(self) -> None:
        (reply, info), _, writer = await self._follow(RuntimeError("down"))
        self.assertEqual(reply, "Space is cool! Kya tumhe stars pasand hain?")
        self.assertFalse(info["checked"])
        writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
