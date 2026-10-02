"""Catch-up: memory work missed while the user was away runs when they come back."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent.cognition.background.idle import MEMORY_FLUSH_JOB, catch_up_pending
from agent.memory_engine.processing.models import MemoryProcessingState
from agent.memory_engine.processing.service import save_processing_state
from storage import (
    JOB_FAILED,
    JOB_PENDING,
    fail_agent_job,
    get_agent_job,
    reset_db,
    save_conversation,
    schedule_agent_job,
)
from agent.shared.clock import utc_now

USER = "catch-up-user"
CHAT_TALK = [
    {"role": "user", "content": "I just moved to Pune for my first job"},
    {"role": "assistant", "content": "Big move! How is it so far?"},
    {"role": "user", "content": "lonely honestly, I don't know anyone here yet"},
]


def key(conversation_id: str) -> str:
    return f"{MEMORY_FLUSH_JOB}:{USER}:{conversation_id}"


class CatchUpTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_unprocessed_chats_get_a_flush_now_processed_ones_do_not(self) -> None:
        save_conversation({"id": "pending-chat", "status": "active", "messages": CHAT_TALK}, USER)
        save_conversation({"id": "done-chat", "status": "active", "messages": CHAT_TALK}, USER)
        save_processing_state(
            MemoryProcessingState(
                conversation_id="done-chat", user_id=USER, processed_through_message_index=2
            )
        )

        queued = catch_up_pending(USER)

        self.assertEqual(queued, ["pending-chat"])
        job = get_agent_job(key("pending-chat"))
        self.assertEqual(job["status"], JOB_PENDING)
        self.assertLessEqual(job["run_after"], utc_now())
        self.assertIsNone(get_agent_job(key("done-chat")))

    def test_a_flush_that_ran_out_of_retries_runs_again(self) -> None:
        save_conversation({"id": "pending-chat", "status": "active", "messages": CHAT_TALK}, USER)
        job = schedule_agent_job(
            kind=MEMORY_FLUSH_JOB,
            dedupe_key=key("pending-chat"),
            user_id=USER,
            conversation_id="pending-chat",
            run_after=utc_now(),
            now=utc_now(),
        )
        fail_agent_job(job, error="provider down", retry_at=None, now=utc_now())
        self.assertEqual(get_agent_job(key("pending-chat"))["status"], JOB_FAILED)

        catch_up_pending(USER)

        revived = get_agent_job(key("pending-chat"))
        self.assertEqual(revived["status"], JOB_PENDING)
        self.assertEqual(revived["attempts"], 0)

    def test_nothing_queued_when_background_memory_is_off(self) -> None:
        save_conversation({"id": "pending-chat", "status": "active", "messages": CHAT_TALK}, USER)
        with patch(
            "agent.cognition.background.idle.background_cognition_enabled", return_value=False
        ):
            self.assertEqual(catch_up_pending(USER), [])
        self.assertIsNone(get_agent_job(key("pending-chat")))


if __name__ == "__main__":
    unittest.main()
