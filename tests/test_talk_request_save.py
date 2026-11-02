"""A how-to-talk request the checker reads in this session is saved as a memory in the same turn,
with the user's message as evidence, so a new chat follows it too. Only requests that quote a
given message count; one that repeats an active request is not saved twice; a temporary chat
saves nothing."""

import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent.context_engine.policy.requests import found_requests, how_to_talk_requests
from agent.context_engine.sources.memories import memory_sources
from agent.memory_engine.memories.models import MemoryKind, MemoryPurpose, MemorySensitivity
from agent.memory_engine.memories.operations import MemoryAddProposal, MemoryAnalysisV3
from agent.memory_engine.memories.talk_requests import without_unclear_requests
from agent.runtime.steps import ReplyJob, follow_requests
from agent.runtime.steps.checks import _bare_acknowledgement
from agent.shared.clock import utc_now
from storage import list_agent_memories, reset_db, save_conversation

USER_ID = "talk-request-user"
CHAT = "talk-request-chat"
NOW = utc_now()
DECLINE = "do not ask stupid questions"


def _chat(*turns: tuple[str, str]) -> list[dict]:
    start = NOW - timedelta(minutes=2 * len(turns))
    return [{"role": role, "content": text, "created_at": (start + timedelta(minutes=2 * i)).isoformat()} for i, (role, text) in enumerate(turns)]


HISTORY = _chat(("user", "hi"), ("assistant", "Hey! Kya kar rahe ho abhi?"), ("user", "bas yaar, din lamba tha"), ("assistant", "Toh abhi kya kar rahe ho?"), ("user", DECLINE), ("assistant", "Theek hai."))
USER_TEXT = "english?"
CHECKER_ANSWER = {
    "broken": [],
    "requests": [
        {"request": "Do not ask what they are doing right now.", "from": DECLINE},
        {"request": "Reply in English.", "from": USER_TEXT},
        {"request": "Made up request.", "from": "a message they never sent"},
    ],
}


class FoundRequestsTest(unittest.TestCase):
    def test_only_requests_that_quote_a_given_message_count(self) -> None:
        self.assertEqual(
            found_requests(CHECKER_ANSWER, [DECLINE, USER_TEXT]),
            [("Do not ask what they are doing right now.", DECLINE), ("Reply in English.", USER_TEXT)],
        )
        self.assertEqual(found_requests({"broken": []}, [DECLINE]), [])
        self.assertEqual(found_requests("junk", [DECLINE]), [])


class SaveInTurnTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PROVIDER": "mock", "AGENT_REQUEST_CHECK": "always"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    async def _turn(self, *, temporary: bool = False) -> dict:
        pending = {"role": "user", "content": USER_TEXT, "created_at": NOW.isoformat()}
        save_conversation({"id": CHAT, "status": "active", "temporary": temporary, "messages": [*HISTORY, pending]}, USER_ID)
        job = ReplyJob(HISTORY, {"conversation_id": CHAT}, AsyncMock(), user_id=USER_ID, conversation_id=CHAT, history=HISTORY, user_text=USER_TEXT)
        with patch("agent.runtime.steps.checks.check_reply_requests", AsyncMock(return_value=CHECKER_ANSWER)):
            _, info = await follow_requests("Sure, English it is.", job)
        return info

    async def test_requests_become_memories_with_the_message_as_evidence(self) -> None:
        info = await self._turn()
        self.assertEqual(info["saved_requests"], 2)
        memories = [m for m in list_agent_memories(USER_ID) if m["kind"] == "procedural"]
        by_text = {m["statement"]: m for m in memories}
        self.assertEqual(set(by_text), {"Do not ask what they are doing right now.", "Reply in English."})
        decline = by_text["Do not ask what they are doing right now."]
        self.assertEqual(decline["evidence"][0]["message_index"], 4)
        self.assertEqual(decline["evidence"][0]["exact_quote"], DECLINE)
        self.assertEqual(by_text["Reply in English."]["evidence"][0]["message_index"], len(HISTORY))
        self.assertEqual(decline["extractor"], "request_check")

        # The same request again, in other words, is not saved twice.
        again = {"broken": [], "requests": [{"request": "Never ask what they are doing right now.", "from": DECLINE}]}
        job = ReplyJob(HISTORY, {"conversation_id": CHAT}, AsyncMock(), user_id=USER_ID, conversation_id=CHAT, history=HISTORY, user_text=USER_TEXT)
        with patch("agent.runtime.steps.checks.check_reply_requests", AsyncMock(return_value=again)):
            _, info = await follow_requests("Okay.", job)
        self.assertEqual(info["saved_requests"], 0)
        self.assertEqual(len([m for m in list_agent_memories(USER_ID) if m["kind"] == "procedural"]), 2)

        # A new chat gets both requests in its how-to-talk block, before any background run.
        requests = how_to_talk_requests(memory_sources(USER_ID, "kal ka plan?"))
        self.assertTrue(any("Reply in English" in line for line in requests), requests)
        self.assertTrue(any("doing right now" in line for line in requests), requests)

    async def test_a_temporary_chat_saves_nothing(self) -> None:
        info = await self._turn(temporary=True)
        self.assertEqual(info["saved_requests"], 0)
        self.assertEqual(list_agent_memories(USER_ID), [])


if __name__ == "__main__":
    unittest.main()


def _batch() -> SimpleNamespace:
    return SimpleNamespace(conversation_id=CHAT, messages=[SimpleNamespace(message_index=2, content=DECLINE)])


def _analysis(*operations) -> MemoryAnalysisV3:
    return MemoryAnalysisV3(decision="write", operations=operations, handoff=None, valid=True)


def _add(kind: MemoryKind, indexes: tuple[int, ...] = (2,)) -> MemoryAddProposal:
    return MemoryAddProposal(kind, frozenset({MemoryPurpose.PERSONALIZATION}), "k", "v", MemorySensitivity.STANDARD, 0.8, 0.7, indexes)


class UnclearRequestsTest(unittest.IsolatedAsyncioTestCase):
    """A rule from the background run stays only if the checker reads a request in its evidence."""

    async def _run(self, answer, *operations):
        check = AsyncMock(side_effect=answer) if isinstance(answer, Exception) else AsyncMock(return_value=answer)
        with patch("agent.providers.check_reply_requests", check):
            return await without_unclear_requests(_batch(), _analysis(*operations)), check

    async def test_a_rule_with_no_request_in_its_evidence_is_dropped(self) -> None:
        result, check = await self._run({"broken": [], "requests": []}, _add(MemoryKind.PROCEDURAL))
        self.assertEqual(result.operations, ())
        self.assertIn(DECLINE, check.await_args.args[0])

    async def test_a_clear_rule_stays(self) -> None:
        operation = _add(MemoryKind.PROCEDURAL)
        result, _ = await self._run({"broken": [], "requests": [{"request": "Reply in English.", "from": DECLINE}]}, operation)
        self.assertEqual(result.operations, (operation,))

    async def test_no_answer_or_a_failure_keeps_it(self) -> None:
        operation = _add(MemoryKind.PROCEDURAL)
        for answer in ({"broken": []}, "junk", RuntimeError("down")):
            result, _ = await self._run(answer, operation)
            self.assertEqual(result.operations, (operation,))

    async def test_other_memories_cost_no_call(self) -> None:
        operation = _add(MemoryKind.SEMANTIC)
        result, check = await self._run({"broken": [], "requests": []}, operation)
        self.assertEqual(result.operations, (operation,))
        check.assert_not_awaited()


class BareAcknowledgementTest(unittest.IsolatedAsyncioTestCase):
    def test_what_counts(self) -> None:
        for reply in ("theek hai.", "ok", "haan, sahi"):
            self.assertTrue(_bare_acknowledgement(reply), reply)
        for reply in ("👍", "theek hai?", "theek hai 👍", "theek hai, tum batao kya hua"):
            self.assertFalse(_bare_acknowledgement(reply), reply)

    async def test_it_is_not_rewritten_whatever_the_checker_says(self) -> None:
        generate = AsyncMock(return_value="rewritten")
        job = ReplyJob(HISTORY, {"conversation_id": CHAT}, generate, requests=["Do not ask questions."], history=HISTORY, user_text="hmm")
        answer = {"broken": ["Do not ask questions."], "requests": []}
        with patch.dict(os.environ, {"AGENT_REQUEST_CHECK": "always"}), patch("agent.runtime.steps.checks.check_reply_requests", AsyncMock(return_value=answer)):
            reply, info = await follow_requests("theek hai.", job)
        self.assertEqual(reply, "theek hai.")
        self.assertEqual(info["broken"], [])
        generate.assert_not_awaited()


class WhatCountsAsARequestTest(unittest.TestCase):
    def test_both_prompts_say_an_opinion_is_not_a_rule(self) -> None:
        from agent.cognition.background.memory_run.prompt_v3 import BACKGROUND_COGNITION_V3_SYSTEM_PROMPT
        from agent.context_engine.policy.requests import REQUEST_CHECK_SYSTEM_PROMPT

        self.assertIn("opinion word", REQUEST_CHECK_SYSTEM_PROMPT)
        self.assertIn("Words of opinion", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)

