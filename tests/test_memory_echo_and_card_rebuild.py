"""Omi's own words never become memories; the card is rebuilt from memories about once a day."""

import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from agent.cognition.background.cards.rebuild import card_memories, card_rebuild_due, rebuild_user_card, schedule_card_rebuild
from agent.memory_engine.memories.echo import is_echo, without_companion_echoes
from agent.memory_engine.memories.validation import validate_memory_analysis_v3
from agent.memory_engine.processing.context import build_memory_batch
from storage import create_agent_memory, get_user_card, reset_db, save_conversation, set_user_card, set_user_timezone
from storage.user_cards import card_rebuilt_at

USER_ID = "echo-card-user"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
CHAT = [
    {"role": "user", "content": "tell how farheen talk?"},
    {"role": "assistant", "content": "From your uploaded chat, Farheen talks in short, compact sentences and loves discussing movies."},
    {"role": "user", "content": "mujhe biryani bahut pasand hai"},
]


def _add(key: str, statement: str, evidence: int) -> dict:
    return {"operation": "add", "memory_kind": "semantic", "purposes": ["profile"], "key": key, "value": statement, "statement": statement, "sensitivity": "standard", "confidence": 0.9, "importance": 0.5, "evidence_message_indexes": [evidence]}


class EchoTest(unittest.TestCase):
    def test_a_memory_made_of_omis_words_is_dropped_and_a_real_one_kept(self) -> None:
        batch = build_memory_batch(conversation_id="c", user_id="u", messages=CHAT)
        analysis = validate_memory_analysis_v3(
            {"operations": [
                _add("people.farheen", "Farheen writes short, compact messages and often discusses movies.", 0),
                _add("food.likes", "Loves biryani.", 2),
                _add("chat_partner.farheen", "Chats with Farheen.", 0),
            ]},
            batch=batch,
        )
        kept = without_companion_echoes(analysis, batch)
        self.assertEqual([op.key for op in kept.operations], ["food.likes"])
        self.assertTrue(any("companion's words" in reason for reason in kept.dropped))
        self.assertTrue(any("only an upload" in reason for reason in kept.dropped))

    def test_a_translation_is_not_an_echo(self) -> None:
        self.assertFalse(is_echo("Dislikes cryptocurrency investments.", "crypto pe paisa nahi lagaunga", {"risky", "market"}))


class CardRebuildTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        set_user_timezone(USER_ID, "Asia/Kolkata")
        save_conversation({"id": "chat", "status": "active", "messages": [{"role": "user", "content": "I live in Pune now, moved from Jaipur"}]}, USER_ID)
        create_agent_memory({
            "user_id": USER_ID, "kind": "semantic", "purposes": ["profile"], "key": "home.city", "value": "Pune",
            "statement": "Lives in Pune.", "confidence": 0.9, "importance": 0.8,
            "evidence": [{"conversation_id": "chat", "message_index": 0, "exact_quote": "I live in Pune now", "observed_at": "2026-10-20T10:00:00+00:00"}],
        })
        set_user_card(USER_ID, "Lives in Jaipur\nPlanning a move back to Jaipur")

    async def test_the_card_is_rewritten_from_memories_only(self) -> None:
        writer = AsyncMock(return_value={"user_card": ["Lives in Pune."]})
        with patch("agent.cognition.background.cards.rebuild.rebuild_user_card_text", writer):
            result = await rebuild_user_card(USER_ID, now=NOW)

        self.assertEqual(result, {"status": "rebuilt", "changed": True})
        self.assertEqual(get_user_card(USER_ID), "Lives in Pune.")
        sent = json.loads(writer.await_args.args[0])
        self.assertEqual(sent["memories"], [{"known": "Lives in Pune.", "kind": "semantic", "date": "2026-10-20"}])
        self.assertIsNotNone(card_rebuilt_at(USER_ID))
        self.assertFalse(card_rebuild_due(USER_ID, now=datetime.now(UTC)))
        self.assertTrue(card_rebuild_due(USER_ID, now=datetime.now(UTC) + timedelta(days=1, minutes=1)))

    async def test_no_card_back_keeps_the_old_one(self) -> None:
        with patch("agent.cognition.background.cards.rebuild.rebuild_user_card_text", AsyncMock(return_value={})):
            self.assertEqual((await rebuild_user_card(USER_ID, now=NOW))["status"], "no_card")
        self.assertEqual(get_user_card(USER_ID), "Lives in Jaipur\nPlanning a move back to Jaipur")

    def test_rebuild_is_queued_once_a_day(self) -> None:
        with patch("agent.cognition.background.cards.rebuild.schedule_job") as schedule:
            self.assertTrue(schedule_card_rebuild(USER_ID))
        schedule.assert_called_once()
        set_user_card(USER_ID, "Lives in Pune.", rebuilt=True)
        with patch("agent.cognition.background.cards.rebuild.schedule_job") as schedule:
            self.assertFalse(schedule_card_rebuild(USER_ID))
        schedule.assert_not_called()

    def test_a_finished_focus_is_marked_over(self) -> None:
        create_agent_memory({
            "user_id": USER_ID, "kind": "semantic", "purposes": ["profile"], "key": "study.transformers", "value": "studying transformers",
            "statement": "Studying transformers.", "focus": True, "confidence": 0.9, "importance": 0.6,
            "evidence": [{"conversation_id": "chat", "message_index": 0, "exact_quote": "I live in Pune now", "observed_at": "2026-08-01T10:00:00+00:00"}],
        })
        study = next(row for row in card_memories(USER_ID, NOW) if row["known"] == "Studying transformers.")
        self.assertEqual(study["focus"], "over")


if __name__ == "__main__":
    unittest.main()
