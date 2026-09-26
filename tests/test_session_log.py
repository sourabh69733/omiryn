"""The per-session log: code splits sessions, the model writes their gist, replies read it."""

import json
import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch

from agent.context_engine.assembly.sources import build_reply_context_sources
from agent.memory_engine.memories.validation import validate_memory_analysis_v3
from agent.memory_engine.processing import build_memory_batch
from agent.memory_engine.processing.models import (
    MemoryHandoff,
    MemoryProcessingState,
    SessionLogEntry,
)
from agent.memory_engine.processing.prompt import memory_batch_prompt
from agent.memory_engine.processing.service import get_processing_state, save_processing_state
from agent.memory_engine.processing.sessions import batch_sessions, merge_session_log
from agent.providers.shared.messages import reply_window
from agent.shared.clock import frozen_time
from storage import reset_db, save_conversation, set_user_timezone

USER_ID = "session-log-user"
CONVERSATION_ID = "session-log-conversation"
WED = "2026-09-23T10:00:00+00:00"
FRI = "2026-09-25T11:58:00+00:00"
FRI_NUDGE = "2026-09-25T15:46:00+00:00"
SAT = "2026-09-26T06:10:00+00:00"


def _message(role: str, content: str, at: str, **extra) -> dict:
    return {"role": role, "content": content, "created_at": at, **extra}


CHAT = [
    _message("user", "planning a Goa trip in December", WED),
    _message("assistant", "Goa in December is lovely.", WED),
    _message("user", "let's play 20 questions, you guess", FRI),
    _message("assistant", "Is it an animal?", FRI),
    _message("assistant", "btw how's the Goa plan going?", FRI_NUDGE, proactive=True),
]


def _batch(messages=CHAT, log: tuple[SessionLogEntry, ...] = ()):
    batch = build_memory_batch(conversation_id=CONVERSATION_ID, user_id=USER_ID, messages=messages)
    assert batch is not None
    return replace(batch, previous_handoff=MemoryHandoff(session_log=log))


class BatchSessionsTest(unittest.TestCase):
    def test_splits_at_long_silences(self) -> None:
        labels, sessions = batch_sessions(_batch(), ())
        self.assertEqual([labels[i] for i in range(5)], ["s1", "s1", "s2", "s2", "s2"])
        self.assertEqual([s.started_at for s in sessions], [WED, FRI])

    def test_continues_the_last_logged_session(self) -> None:
        logged = SessionLogEntry(started_at=FRI, ended_at=FRI, gist="Played 20 questions.")
        later = [_message("user", "is it a cat?", "2026-09-25T12:05:00+00:00")]
        _, sessions = batch_sessions(_batch(later, (logged,)), (logged,))
        self.assertEqual(sessions[0].started_at, FRI)


class MergeSessionLogTest(unittest.TestCase):
    def test_writes_sessions_with_new_messages_and_drops_bad_items(self) -> None:
        log = merge_session_log(
            [
                {"session": "s2", "gist": "  Played 20 questions; the companion asked if it was an animal. ",
                 "unfinished": "the 20 questions game"},
                {"session": "s9", "gist": "unknown session"},
                {"session": "s1", "gist": ""},
                "not an object",
            ],
            batch=_batch(),
            previous=(),
        )
        self.assertEqual([entry.started_at for entry in log], [FRI])
        self.assertEqual(log[0].unfinished, "the 20 questions game")
        self.assertEqual(log[0].ended_at, FRI_NUDGE)

    def test_missing_log_keeps_the_previous_one(self) -> None:
        previous = (SessionLogEntry(started_at=WED, ended_at=WED, gist="Goa trip plans."),)
        self.assertEqual(merge_session_log(None, batch=_batch(), previous=previous), previous)


class SessionLogFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": CHAT}, USER_ID)
        set_user_timezone(USER_ID, "Asia/Kolkata")

    def test_prompt_marks_sessions_and_companion_initiated_messages(self) -> None:
        payload = json.loads(memory_batch_prompt(_batch(), [], "Asia/Kolkata"))
        self.assertEqual(payload["messages"][2]["session"], "s2")
        self.assertTrue(payload["messages"][4]["initiated_by_companion"])
        self.assertNotIn("initiated_by_companion", payload["messages"][3])
        self.assertEqual(payload["sessions"][1]["started_at"], "2026-09-25T17:28+05:30")

    def test_validated_log_is_saved_and_shown_on_the_next_reply(self) -> None:
        raw = {
            "decision": "no_change",
            "operations": [],
            "handoff": {
                "summary": "", "active_people": [], "active_topics": [], "unresolved_references": [],
                "session_log": [
                    {"session": "s1", "gist": "Talked about a Goa trip in December."},
                    {"session": "s2", "gist": "Started a 20 questions game.",
                     "unfinished": "the game; the user had not answered 'Is it an animal?'"},
                ],
            },
        }
        result = validate_memory_analysis_v3(raw, batch=_batch())
        self.assertTrue(result.valid, result.errors)
        save_processing_state(
            MemoryProcessingState(conversation_id=CONVERSATION_ID, user_id=USER_ID, handoff=result.handoff)
        )
        self.assertEqual(len(get_processing_state(CONVERSATION_ID, USER_ID).handoff.session_log), 2)

        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}), frozen_time(
            datetime.fromisoformat(SAT)
        ):
            sources = build_reply_context_sources(CONVERSATION_ID, None, "what were we doing last time?", USER_ID)
        block = next(s["content"] for s in sources if s["source_type"] == "recent_sessions")
        self.assertIn("- Wednesday 23 Sep, 3:30 pm (2 days ago): Talked about a Goa trip in December.", block)
        self.assertIn(
            "- Friday 25 Sep, 5:28 pm (14 hours ago): Started a 20 questions game. Left open: the game;",
            block,
        )


class ReturnHistoryTest(unittest.TestCase):
    def test_previous_session_tail_stays_in_the_chat_history(self) -> None:
        messages = [*CHAT, _message("user", "hey hi", SAT)]
        contents = [m["content"] for m in reply_window(messages, summarized_through=4)]
        self.assertIn("Is it an animal?", contents)
        self.assertNotIn("planning a Goa trip in December", contents)


if __name__ == "__main__":
    unittest.main()
