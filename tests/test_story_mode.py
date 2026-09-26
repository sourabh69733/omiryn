"""Story autoplay: parts follow on their own while the user listens, with check-ins and a stop."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import storage
from agent.context_engine.conversation_engine.policy.replies import strip_story_end
from agent.jobs.worker import JobWorker
from agent.proactive.story import run_story_part_job
from agent.runtime.orchestrator import _turn_notes, run_agent_turn
from agent.runtime.story_mode import (
    STORY_PART_JOB,
    auto_parts_since_user,
    story_part_block_reason,
)
from realtime import realtime_hub

USER_ID = "story-user"
CONVERSATION_ID = "story-conversation"
JOB_KEY = f"{STORY_PART_JOB}:{USER_ID}:{CONVERSATION_ID}"
STORY_START = [
    {"role": "user", "content": "tell me a story about a lighthouse keeper"},
    {"role": "assistant", "content": "Mira kept the lighthouse at Kovalam.", "story": True},
    {"role": "assistant", "content": "One stormy night, a light blinked back at her.", "story": True},
]


def _auto(part: int, content: str = "The boat came closer.") -> dict:
    return {"role": "assistant", "content": content, "story": True, "story_auto": part}


class StoryPolicyTest(unittest.TestCase):
    def test_marker_is_removed_in_any_spelling(self) -> None:
        for text in ("The end. <story_end>", "The end. [story_end]", "The end.</story end>"):
            with self.subTest(text=text):
                self.assertEqual(strip_story_end(text), ("The end.", True))
        self.assertEqual(strip_story_end("Not yet."), ("Not yet.", False))

    def test_counts_automatic_parts_since_the_user_spoke(self) -> None:
        self.assertEqual(auto_parts_since_user(STORY_START), 0)
        self.assertEqual(auto_parts_since_user([*STORY_START, _auto(1), _auto(2)]), 2)
        after_user = [*STORY_START, _auto(2), {"role": "user", "content": "then?"}, *STORY_START[1:]]
        self.assertEqual(auto_parts_since_user(after_user), 0)

    def test_when_the_story_may_go_on(self) -> None:
        self.assertIsNone(story_part_block_reason(STORY_START))
        cases = {
            "not_telling_a_story": [*STORY_START, {"role": "user", "content": "stop"}],
            "story_ended": [*STORY_START, {**_auto(1), "story_end": True}],
            "waiting_for_user": [*STORY_START, _auto(1, "Still with me?")],
            "check_in_due": [*STORY_START, _auto(1), _auto(2), _auto(3)],
        }
        for reason, messages in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(story_part_block_reason(messages), reason)

    def test_autoplay_changes_how_a_story_part_ends(self) -> None:
        with patch.dict(os.environ, {"AGENT_STORY_AUTOPLAY": "true"}):
            [note] = _turn_notes(1, ("story_or_long_reply",))
            self.assertIn("without asking whether to go on", note["content"])
            self.assertIn("<story_end>", note["content"])
        with patch.dict(os.environ, {"AGENT_STORY_AUTOPLAY": "false"}):
            [note] = _turn_notes(1, ("story_or_long_reply",))
            self.assertIn("want more?", note["content"])


class _Socket:
    async def send_json(self, payload: dict) -> None:
        pass


class StoryJobTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        storage.reset_db()
        await realtime_hub.reset()
        self.env = patch.dict(
            os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}
        )
        self.env.start()

    async def asyncTearDown(self) -> None:
        self.env.stop()
        await realtime_hub.reset()

    def _save(self, messages: list[dict]) -> None:
        storage.save_conversation(
            {"id": CONVERSATION_ID, "status": "active", "messages": messages}, USER_ID
        )

    async def _watch(self) -> None:
        connection = await realtime_hub.register(_Socket(), USER_ID)
        await realtime_hub.subscribe(connection, "conversation", CONVERSATION_ID)

    async def _run_job(self, reply: str) -> tuple[bool, AsyncMock]:
        generate = AsyncMock(return_value=reply)
        with patch("agent.proactive.story.generate_initiative_text", generate):
            sent = await run_story_part_job({"user_id": USER_ID, "conversation_id": CONVERSATION_ID})
        return sent, generate

    def _messages(self) -> list[dict]:
        return storage.get_conversation(CONVERSATION_ID, USER_ID)["messages"]

    async def test_a_story_turn_schedules_the_next_part(self) -> None:
        self._save(STORY_START[1:2])
        story = "Mira kept the lighthouse.<next_message>A light blinked back at her."
        with patch("agent.runtime.orchestrator.generate_agent_reply", AsyncMock(return_value=story)):
            result = await run_agent_turn(
                conversation_id=CONVERSATION_ID,
                messages=STORY_START[1:2],
                user_text="tell me a story about a lighthouse keeper",
                user_id=USER_ID,
                user_profile={},
                model=None,
                agent_mode="know_me",
                agent_tone="auto",
                style_source_id=None,
            )
        self.assertTrue(all(m.get("story") for m in result.messages[-2:]))
        self.assertIsNotNone(storage.get_agent_job(JOB_KEY))

    async def test_part_is_sent_while_the_user_watches_and_schedules_the_next(self) -> None:
        self._save(STORY_START)
        await self._watch()

        sent, generate = await self._run_job("The light was a boat.<next_message>Someone waved.")

        self.assertTrue(sent)
        new = self._messages()[-2:]
        self.assertEqual([m["story_auto"] for m in new], [1, 1])
        self.assertIn("without asking anything", generate.await_args.kwargs["instructions"])
        self.assertIsNotNone(storage.get_agent_job(JOB_KEY))

    async def test_third_part_checks_in_and_waits(self) -> None:
        self._save([*STORY_START, _auto(1), _auto(2)])
        await self._watch()

        sent, generate = await self._run_job("She rowed out.<next_message>Still with me?")

        self.assertTrue(sent)
        self.assertIn("check-in", generate.await_args.kwargs["instructions"])
        self.assertIsNotNone(story_part_block_reason(self._messages()))
        self.assertIsNone(storage.get_agent_job(JOB_KEY))  # waits for the user

    async def test_ending_marks_the_story_done_and_hides_the_marker(self) -> None:
        self._save(STORY_START)
        await self._watch()

        await self._run_job("And the lighthouse never went dark again. <story_end>")

        last = self._messages()[-1]
        self.assertTrue(last["story_end"])
        self.assertNotIn("story_end", last["content"])
        self.assertEqual(story_part_block_reason(self._messages()), "story_ended")

    async def test_pauses_when_the_user_is_not_watching(self) -> None:
        self._save(STORY_START)
        sent, generate = await self._run_job("More story.")
        self.assertFalse(sent)
        generate.assert_not_awaited()

    async def test_stops_once_the_user_wrote_something_else(self) -> None:
        self._save([*STORY_START, {"role": "user", "content": "stop, tell me about your day"}])
        await self._watch()
        sent, generate = await self._run_job("More story.")
        self.assertFalse(sent)
        generate.assert_not_awaited()

    async def test_worker_runs_story_jobs(self) -> None:
        handled = AsyncMock()
        worker = JobWorker(handlers={STORY_PART_JOB: handled})
        with patch.dict(os.environ, {"AGENT_STORY_PART_MIN_SECONDS": "0", "AGENT_STORY_PART_MAX_SECONDS": "0"}):
            from agent.runtime.story_mode import schedule_story_part

            schedule_story_part(USER_ID, CONVERSATION_ID)
        await asyncio.sleep(0)
        self.assertEqual(await worker.run_once(), 1)
        handled.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
