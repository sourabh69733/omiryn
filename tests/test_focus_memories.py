"""Current-focus memories stay fresh while mentioned, fade after weeks of silence, then archive."""

import unittest
from datetime import datetime, timedelta, timezone

from agent.context_engine.assembly.sources import _memory_time_note
from agent.memory_engine.memories.focus import focus_state, without_focus_lines
from agent.memory_engine.memories.retrieval import _reply_eligible, might_fit_memories
from agent.memory_engine.memories.validation import _validate_add, _ADD_FIELDS
from storage import create_agent_memory, list_agent_memories, reset_db, save_conversation

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
USER_ID = "focus-user"


def _memory(days_ago: float, *, focus: bool = True) -> dict:
    said = (NOW - timedelta(days=days_ago)).isoformat()
    return {
        "kind": "semantic", "status": "active", "focus": focus, "allowed_uses": ["reply_context"],
        "sensitivity": "standard", "statement": "Studying transformers.", "created_at": said,
        "evidence": [{"observed_at": said}],
    }


class FocusFreshnessTest(unittest.TestCase):
    def test_fresh_then_fading_then_archived(self) -> None:
        self.assertEqual(focus_state(_memory(3), NOW), "current")
        self.assertEqual(focus_state(_memory(20), NOW), "fading")
        self.assertEqual(focus_state(_memory(50), NOW), "archived")
        self.assertIsNone(focus_state(_memory(50, focus=False), NOW))

    def test_a_new_mention_refreshes_it(self) -> None:
        memory = _memory(50)
        memory["evidence"].append({"observed_at": (NOW - timedelta(days=1)).isoformat()})
        self.assertEqual(focus_state(memory, NOW), "current")

    def test_replies_get_the_freshness_and_skip_an_archived_focus(self) -> None:
        zone = timezone.utc
        self.assertIn("a current focus", _memory_time_note(_memory(3), zone, NOW))
        self.assertIn("may be over", _memory_time_note(_memory(20), zone, NOW))
        self.assertTrue(_reply_eligible(_memory(20), NOW))
        self.assertFalse(_reply_eligible(_memory(50), NOW))
        # A lasting fact is never archived, however old.
        self.assertTrue(_reply_eligible(_memory(400, focus=False), NOW))

    def test_the_model_can_mark_a_focus(self) -> None:
        raw = {
            "operation": "add", "memory_kind": "semantic", "purposes": ["personalization"], "key": "learning.topic",
            "value": "transformers", "statement": "Studying transformers.", "sensitivity": "standard",
            "confidence": 0.9, "importance": 0.5, "focus": True, "evidence_message_indexes": [0],
        }
        proposal, errors = _validate_add(raw, eligible_indexes={0}, expected_operation="add", allowed_fields=_ADD_FIELDS)
        self.assertEqual(errors, [])
        self.assertTrue(proposal.focus)


class FocusCardTest(unittest.TestCase):
    def test_card_lines_that_restate_a_focus_go_and_the_rest_stay(self) -> None:
        focus = [{"statement": "Is studying transformers in ML.", "value": "studying transformers in ml"},
                 {"statement": "Learning Rajasthani cooking in Jaipur.", "value": "rajasthani cooking"}]
        card = "Lives in Jaipur.\nWorks as a backend developer.\nCurrently studying transformers in machine learning.\nPrefers Hinglish."
        self.assertEqual(without_focus_lines(card, focus), "Lives in Jaipur.\nWorks as a backend developer.\nPrefers Hinglish.")


class FocusStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": "chat", "status": "active", "messages": [{"role": "user", "content": "studying transformers"}]}, USER_ID)

    def _add(self, days_ago: float) -> str:
        said = (NOW - timedelta(days=days_ago)).isoformat()
        return create_agent_memory(
            {
                "user_id": USER_ID, "kind": "semantic", "purposes": ["personalization"], "key": f"focus.{days_ago}",
                "value": "transformers", "statement": "Studying transformers.", "focus": True, "importance": 0.9,
                "evidence": [{"conversation_id": "chat", "message_index": 0, "exact_quote": "studying transformers", "observed_at": said}],
            }
        )["id"]

    def test_focus_is_stored_and_a_fading_one_is_not_offered_as_a_topic(self) -> None:
        fresh, fading = self._add(2), self._add(20)
        self.assertTrue(all(memory["focus"] for memory in list_agent_memories(USER_ID)))
        offered = {memory["id"] for memory in might_fit_memories(USER_ID, exclude_ids=set(), recently_offered=set(), now=NOW)}
        self.assertIn(fresh, offered)
        self.assertNotIn(fading, offered)

    def test_something_said_this_session_is_not_offered_again(self) -> None:
        just_said = self._add(0.05)  # about an hour ago
        offered = {memory["id"] for memory in might_fit_memories(USER_ID, exclude_ids=set(), recently_offered=set(), now=NOW)}
        self.assertNotIn(just_said, offered)

    def test_a_finished_event_told_after_it_happened_is_not_offered(self) -> None:
        def event(key: str, happened_days_ago: float, told_days_ago: float) -> str:
            told = (NOW - timedelta(days=told_days_ago)).isoformat()
            return create_agent_memory(
                {
                    "user_id": USER_ID, "kind": "episodic", "purposes": ["personalization"], "key": key,
                    "value": key, "statement": f"{key}.", "importance": 0.9,
                    "occurred_at": (NOW - timedelta(days=happened_days_ago)).isoformat(),
                    "evidence": [{"conversation_id": "chat", "message_index": 0, "exact_quote": "studying transformers", "observed_at": told}],
                }
            )["id"]

        finished = event("Completed the course", 1, 1)
        told_ahead = event("Had an interview", 1, 2)
        offered = {memory["id"] for memory in might_fit_memories(USER_ID, exclude_ids=set(), recently_offered=set(), now=NOW)}
        self.assertNotIn(finished, offered)
        self.assertIn(told_ahead, offered)


if __name__ == "__main__":
    unittest.main()
