"""The companion's notes about what it said: validated, written in the background, shown later."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.prompt_v3 import BACKGROUND_COGNITION_V3_SYSTEM_PROMPT
from agent.cognition.background.service import run_background_cognition
from agent.context_engine.assembly.sources import build_reply_context_sources
from agent.memory_engine.memories.self_notes import validate_self_notes
from agent.memory_engine.processing import build_memory_batch
from agent.shared.clock import frozen_time
from agent.shared.timeline import parse_time
from storage import (
    add_self_notes,
    delete_conversation,
    list_active_self_notes,
    reset_db,
    save_conversation,
)

USER_ID = "self-notes-user"
CONVERSATION_ID = "self-notes-conversation"
MESSAGES = [
    {"role": "user", "content": "first date: coffee or a long walk?"},
    {"role": "assistant", "content": "Long walk, easily. Coffee feels like an interview."},
    {"role": "user", "content": "my interview is on friday, wish me luck"},
    {"role": "assistant", "content": "Good luck! I'll ask you how it went on Friday."},
]


def _batch():
    batch = build_memory_batch(conversation_id=CONVERSATION_ID, user_id=USER_ID, messages=MESSAGES)
    assert batch is not None
    return batch


def _add(**changes):
    item = {"operation": "add", "kind": "opinion", "text": "Prefers long walks.", "message_index": 1}
    item.update(changes)
    return item


class ValidateSelfNotesTest(unittest.TestCase):
    def test_keeps_notes_backed_by_new_companion_messages(self) -> None:
        changes = validate_self_notes(
            [
                _add(),
                _add(kind="promise", text="Ask how the interview went.", message_index=3,
                     due_at="2026-09-18T12:00:00+05:30"),
            ],
            batch=_batch(),
            active_note_ids=set(),
        )
        self.assertEqual([note.kind for note in changes.adds], ["opinion", "promise"])
        self.assertEqual(changes.adds[1].due_at.isoformat(), "2026-09-18T12:00:00+05:30")

    def test_drops_bad_items_but_keeps_the_rest(self) -> None:
        changes = validate_self_notes(
            [
                _add(message_index=0),  # a user message
                _add(kind="memory"),
                _add(text="x" * 201),
                {"operation": "resolve", "target_note_id": "unknown", "status": "done"},
                _add(),
            ],
            batch=_batch(),
            active_note_ids=set(),
        )
        self.assertEqual(len(changes.adds), 1)
        self.assertEqual(len(changes.dropped), 4)

    def test_only_promises_carry_a_due_date(self) -> None:
        changes = validate_self_notes(
            [_add(due_at="2026-09-18T12:00:00+05:30")], batch=_batch(), active_note_ids=set()
        )
        self.assertIsNone(changes.adds[0].due_at)

    def test_resolves_active_notes_once(self) -> None:
        resolve = {"operation": "resolve", "target_note_id": "n1", "status": "done"}
        changes = validate_self_notes([resolve, resolve], batch=_batch(), active_note_ids={"n1"})
        self.assertEqual(len(changes.resolves), 1)

    def test_non_list_means_no_change(self) -> None:
        self.assertTrue(validate_self_notes(None, batch=_batch(), active_note_ids=set()).empty)

    def test_prompt_forbids_invented_human_experiences(self) -> None:
        self.assertIn("Never note an invented human experience", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)


class SelfNotesFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": MESSAGES}, USER_ID)
        self.env = patch.dict(
            os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    async def _run(self, self_notes: list) -> AsyncMock:
        response = {
            "decision": "no_change",
            "operations": [],
            "thread_operation": {"operation": "none"},
            "handoff": {"summary": "", "active_people": [], "active_topics": [],
                        "unresolved_references": []},
            "self_notes": self_notes,
        }
        with patch(
            "agent.cognition.background.service.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=response,
        ) as provider:
            result = await run_background_cognition(CONVERSATION_ID, USER_ID, MESSAGES)
        self.assertNotIn(result["status"], {"live_invalid", "live_error"}, result)
        return provider

    async def test_background_adds_notes_and_later_resolves_them(self) -> None:
        await self._run(
            [_add(), _add(kind="promise", text="Ask how the interview went.", message_index=3)]
        )
        notes = list_active_self_notes(USER_ID)
        self.assertEqual({note["kind"] for note in notes}, {"opinion", "promise"})

        MESSAGES.extend([{"role": "user", "content": "hi again"},
                         {"role": "assistant", "content": "How did the interview go?"}])
        try:
            promise = next(note for note in notes if note["kind"] == "promise")
            provider = await self._run(
                [{"operation": "resolve", "target_note_id": promise["id"], "status": "done"}]
            )
        finally:
            del MESSAGES[4:]
        sent = json.loads(provider.await_args.args[0])["existing_self_notes"]
        self.assertEqual({note["id"] for note in sent}, {note["id"] for note in notes})
        self.assertEqual([note["kind"] for note in list_active_self_notes(USER_ID)], ["opinion"])

    def test_replayed_notes_are_not_added_twice(self) -> None:
        note = {"id": "fixed", "kind": "joke", "text": "Calls Bruno the drama queen.", "message_index": 1}
        self.assertEqual(add_self_notes(USER_ID, CONVERSATION_ID, [note]), 1)
        self.assertEqual(add_self_notes(USER_ID, CONVERSATION_ID, [note]), 0)

    def test_context_shows_promises_always_and_opinions_when_relevant(self) -> None:
        add_self_notes(USER_ID, CONVERSATION_ID, [
            {"id": "a", "kind": "opinion", "text": "Prefers long walks over coffee for a first date.",
             "message_index": 1},
            {"id": "b", "kind": "promise", "text": "Ask how the interview went.",
             "message_index": 3, "due_at": parse_time("2026-09-18T12:00:00+05:30")},
        ])
        with frozen_time(parse_time("2026-09-16T20:00:00+05:30")):
            unrelated = self._notes_content("random stuff")
            related = self._notes_content("thinking about a first date walk")
        self.assertIn("promise: Ask how the interview went. (due Fri 18 Sep 2026, this Friday, in 2 days)", unrelated)
        self.assertNotIn("long walks", unrelated)
        self.assertIn("opinion: Prefers long walks", related)

    def test_notes_go_with_their_conversation(self) -> None:
        add_self_notes(USER_ID, CONVERSATION_ID, [
            {"id": "a", "kind": "joke", "text": "Coffee dates are interviews.", "message_index": 1},
        ])
        delete_conversation(CONVERSATION_ID, USER_ID)
        self.assertEqual(list_active_self_notes(USER_ID), [])

    def _notes_content(self, user_text: str) -> str:
        sources = build_reply_context_sources(CONVERSATION_ID, None, user_text, USER_ID)
        return next(
            (s["content"] for s in sources if s["source_type"] == "agent_self_notes"), ""
        )


if __name__ == "__main__":
    unittest.main()
