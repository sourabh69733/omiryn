import json
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from agent.cognition.background.prompt_v3 import BACKGROUND_COGNITION_V3_SYSTEM_PROMPT
from agent.context_engine.assembly.sources import build_reply_context_sources
from agent.memory_engine.memories.validation import (
    MAX_CONVERSATION_SUMMARY_CHARS,
    validate_memory_analysis_v3,
)
from agent.memory_engine.processing import build_memory_batch
from agent.memory_engine.processing.models import MemoryHandoff, MemoryProcessingState
from agent.memory_engine.processing.prompt import memory_batch_prompt
from agent.memory_engine.processing.service import get_processing_state, save_processing_state
from agent.providers.shared.messages import reply_window, summarized_through
from storage import reset_db, save_conversation

USER_ID = "summary-user"
CONVERSATION_ID = "summary-conversation"
PREVIOUS = "On Mon 21 Sep the user said the interview is on Friday."


def _batch(previous_summary: str = PREVIOUS):
    batch = build_memory_batch(
        conversation_id=CONVERSATION_ID,
        user_id=USER_ID,
        messages=[{"role": "user", "content": "The interview went really well!"}],
    )
    assert batch is not None
    return replace(
        batch, previous_handoff=MemoryHandoff(conversation_summary=previous_summary)
    )


def _no_change(handoff_extra: dict) -> dict:
    return {
        "decision": "no_change",
        "operations": [],
        "handoff": {
            "summary": "",
            "active_people": [],
            "active_topics": [],
            "unresolved_references": [],
            **handoff_extra,
        },
    }


class SummaryValidationTest(unittest.TestCase):
    def test_new_summary_replaces_previous(self) -> None:
        result = validate_memory_analysis_v3(
            _no_change({"conversation_summary": "  The interview went well.  "}), batch=_batch()
        )
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.handoff.conversation_summary, "The interview went well.")

    def test_missing_or_blank_summary_keeps_previous(self) -> None:
        for extra in ({}, {"conversation_summary": "   "}, {"conversation_summary": None}):
            with self.subTest(extra=extra):
                result = validate_memory_analysis_v3(_no_change(extra), batch=_batch())
                self.assertTrue(result.valid, result.errors)
                self.assertEqual(result.handoff.conversation_summary, PREVIOUS)

    def test_overlong_summary_is_trimmed_at_a_sentence_without_failing_the_batch(self) -> None:
        long_summary = "The user likes tea. " * 200
        result = validate_memory_analysis_v3(
            _no_change({"conversation_summary": long_summary}), batch=_batch()
        )
        self.assertTrue(result.valid, result.errors)
        summary = result.handoff.conversation_summary
        self.assertLessEqual(len(summary), MAX_CONVERSATION_SUMMARY_CHARS)
        self.assertTrue(summary.endswith("tea."))

    def test_prompt_and_batch_carry_the_summary(self) -> None:
        payload = json.loads(memory_batch_prompt(_batch(), []))
        self.assertEqual(payload["previous_handoff"]["conversation_summary"], PREVIOUS)
        self.assertIn("conversation_summary", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)


class ReplyWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.messages = [{"role": "user", "content": f"m{index}"} for index in range(40)]

    def test_without_summary_all_messages_are_kept(self) -> None:
        self.assertEqual(reply_window(self.messages, None), self.messages)

    @patch("agent.providers.shared.messages.RECENT_CHAT_MESSAGE_LIMIT", 24)
    def test_summarized_messages_outside_the_window_are_dropped(self) -> None:
        window = reply_window(self.messages, 30)
        self.assertEqual(len(window), 24)
        self.assertEqual(window[0]["content"], "m16")

    @patch("agent.providers.shared.messages.RECENT_CHAT_MESSAGE_LIMIT", 24)
    def test_unsummarized_messages_are_never_dropped(self) -> None:
        window = reply_window(self.messages, 5)
        self.assertEqual(window[0]["content"], "m6")

    def test_summarized_through_reads_the_summary_source(self) -> None:
        sources = [
            {"source_type": "agent_memories_v3", "metadata": {}},
            {"source_type": "conversation_summary", "metadata": {"processed_through_message_index": 12}},
        ]
        self.assertEqual(summarized_through(sources), 12)
        self.assertIsNone(summarized_through(sources[:1]))


class SummaryContextSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation(
            {
                "id": CONVERSATION_ID,
                "status": "active",
                "messages": [{"role": "user", "content": "hi"}] * 4,
            },
            USER_ID,
        )

    def test_summary_round_trips_and_reaches_reply_context_in_v3_only(self) -> None:
        save_processing_state(
            MemoryProcessingState(
                conversation_id=CONVERSATION_ID,
                user_id=USER_ID,
                processed_through_message_index=3,
                handoff=MemoryHandoff(conversation_summary=PREVIOUS),
            )
        )
        self.assertEqual(
            get_processing_state(CONVERSATION_ID, USER_ID).handoff.conversation_summary, PREVIOUS
        )

        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"}):
            v3 = build_reply_context_sources(CONVERSATION_ID, None, "how did it go", USER_ID)
        with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v2"}):
            v2 = build_reply_context_sources(CONVERSATION_ID, None, "how did it go", USER_ID)

        summary = next(s for s in v3 if s["source_type"] == "conversation_summary")
        self.assertIn(PREVIOUS, summary["content"])
        self.assertEqual(summarized_through(v3), 3)
        self.assertIsNone(summarized_through(v2))


if __name__ == "__main__":
    unittest.main()
