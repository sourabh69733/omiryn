"""The reply check against how the user asked to be talked to."""

import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.policy.requests import broken_requests, how_to_talk_requests
from agent.runtime.steps import ReplyJob, follow_requests

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
        job = ReplyJob(
            [{"role": "user", "content": "space ke baare mein batao"}], ARGS, writer, requests=requests,
            previous_replies=["Haan! Kya tumhe stars pasand hain?"],
        )
        with patch("agent.runtime.steps.checks.check_reply_requests", checker):
            result = await follow_requests("Space is cool! Kya tumhe stars pasand hain?", job)
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

    async def test_a_request_rewrite_drops_a_question_already_asked(self) -> None:
        """The rewrite often brings back a question from its own history; it is dropped like after a freshness rewrite."""
        (reply, info), _, _ = await self._follow(
            {"broken": ["Wants no questions from the companion."]},
            rewrite="Venus ka din lamba hai. Kya tumhe stars pasand hain?",
        )
        self.assertEqual(reply, "Venus ka din lamba hai.")

    async def test_a_failed_check_keeps_the_draft(self) -> None:
        (reply, info), _, writer = await self._follow(RuntimeError("down"))
        self.assertEqual(reply, "Space is cool! Kya tumhe stars pasand hain?")
        self.assertFalse(info["checked"])
        writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class RecentRequestsTest(unittest.IsolatedAsyncioTestCase):
    """A request made in this session holds before it is saved (seen live: one question asked 5 times)."""

    HISTORY = [
        {"role": "user", "content": "hi", "created_at": "2026-10-28T08:00:00+00:00"},
        {"role": "assistant", "content": "Kya kar rahe ho abhi?", "created_at": "2026-10-28T08:00:05+00:00"},
        {"role": "user", "content": "do not ask stupid questions", "created_at": "2026-10-28T08:01:00+00:00"},
    ]

    def test_session_user_messages_are_read_newest_last(self) -> None:
        from agent.context_engine.policy.requests import recent_user_requests

        old = {"role": "user", "content": "yesterday's chat", "created_at": "2026-10-27T08:00:00+00:00"}
        self.assertEqual(
            recent_user_requests([old, *self.HISTORY], "english?"),
            ["hi", "do not ask stupid questions", "english?"],
        )

    async def test_a_request_from_this_session_is_checked_without_saved_ones(self) -> None:
        checker = AsyncMock(return_value={"broken": ["do not ask stupid questions"]})
        writer = AsyncMock(return_value="Theek hai, chill karte hain.")
        # As the orchestrator does: the asked questions carry what the user said to each.
        from agent.context_engine.policy.asked_questions import asked_questions

        job = ReplyJob(list(self.HISTORY), ARGS, writer, history=list(self.HISTORY), user_text="ok", asked=asked_questions(self.HISTORY))
        with patch("agent.runtime.steps.checks.check_reply_requests", checker):
            reply, info = await follow_requests("Acha, toh kya kar rahe ho abhi?", job)

        self.assertEqual(reply, "Theek hai, chill karte hain.")
        self.assertEqual(info["broken"], ["do not ask stupid questions"])
        self.assertIn('"recent_user_messages": ["hi", "do not ask stupid questions", "ok"]', checker.await_args.args[0])
        self.assertIn("do not ask stupid questions", writer.await_args.args[0][-1]["content"])
