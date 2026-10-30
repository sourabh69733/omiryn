"""The request check runs only when a code fact says the draft could break a request.

It is one model call per reply it runs for, so a reply with nothing to check skips it.
"""

import os
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from agent.context_engine.policy.asked_questions import asked_questions
from agent.context_engine.policy.requests import request_check_reason
from agent.runtime.steps import ReplyJob, follow_requests, request_check_mode
from agent.shared.clock import utc_now

NOW = utc_now()


def _chat(*turns: tuple[str, str]) -> list[dict]:
    start = NOW - timedelta(minutes=2 * len(turns))
    return [{"role": role, "content": text, "created_at": (start + timedelta(minutes=2 * i)).isoformat()} for i, (role, text) in enumerate(turns)]


PLAIN = _chat(("user", "hi"), ("assistant", "Hey! Aaj din kaisa tha tumhara?"), ("user", "theek tha, office busy tha"))
ANSWERED = asked_questions(PLAIN, now=NOW)


class ReasonTest(unittest.TestCase):
    def test_nothing_to_check_means_no_call(self) -> None:
        self.assertIsNone(request_check_reason("Busy din tha phir.", [], ["hi", "theek tha, office busy tha"], ANSWERED))

    def test_saved_requests_always_run_it(self) -> None:
        self.assertEqual(request_check_reason("Busy din tha phir.", ["Prefers short replies."], [], []), "saved_requests")

    def test_a_question_after_an_answered_or_brushed_off_question_runs_it(self) -> None:
        self.assertEqual(request_check_reason("Aur office mein kya hua?", [], [], ANSWERED), "question_after_asked")
        unanswered = asked_questions(_chat(("assistant", "Aaj din kaisa tha tumhara?")), now=NOW)
        self.assertIsNone(request_check_reason("Aur kya chal raha hai?", [], [], unanswered))

    def test_a_constraint_or_feedback_in_the_session_runs_it(self) -> None:
        self.assertEqual(request_check_reason("Okay.", [], ["hi", "please don't ask questions"], []), "request_in_session")
        self.assertEqual(request_check_reason("Okay.", [], ["too many questions yaar"], []), "request_in_session")

    def test_modes(self) -> None:
        for value, mode in (("", "auto"), ("auto", "auto"), ("always", "always"), ("true", "always"), ("false", "false"), ("off", "false")):
            with patch.dict(os.environ, {"AGENT_REQUEST_CHECK": value}):
                self.assertEqual(request_check_mode(), mode, value)


class FollowRequestsGateTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, reply: str, env: dict[str, str], **job_fields):
        checker = AsyncMock(return_value={"broken": []})
        job = ReplyJob(PLAIN, {"conversation_id": "c"}, AsyncMock(), history=PLAIN[:-1], user_text="theek tha, office busy tha", **job_fields)
        with patch.dict(os.environ, env), patch("agent.runtime.steps.checks.check_reply_requests", checker):
            result = await follow_requests(reply, job)
        return result, checker

    async def test_a_plain_reply_skips_the_call(self) -> None:
        (reply, info), checker = await self._run("Busy din tha phir.", {"AGENT_REQUEST_CHECK": "auto"}, asked=ANSWERED)
        self.assertEqual(info, {"checked": False, "skipped": "no_signal"})
        checker.assert_not_called()

    async def test_a_question_after_an_answered_one_is_checked(self) -> None:
        (reply, info), checker = await self._run("Aur office mein kya hua?", {"AGENT_REQUEST_CHECK": "auto"}, asked=ANSWERED)
        self.assertEqual(info["reason"], "question_after_asked")
        checker.assert_awaited_once()

    async def test_always_checks_every_reply(self) -> None:
        (reply, info), checker = await self._run("Busy din tha phir.", {"AGENT_REQUEST_CHECK": "always"}, asked=ANSWERED)
        self.assertEqual(info["reason"], "always")
        checker.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
