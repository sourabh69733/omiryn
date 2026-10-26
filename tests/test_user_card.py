"""The per-user card: validated, written by background cognition, shown on every reply."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.memory_run.prompt_v3 import BACKGROUND_COGNITION_V3_SYSTEM_PROMPT
from agent.cognition.background.memory_run.service import run_background_cognition
from agent.context_engine.assembly.sources import build_reply_context_sources
from agent.memory_engine.memories.user_card import MAX_USER_CARD_CHARS, validate_user_card, without_replaced_lines
from storage import create_agent_memory, get_user_card, reset_db, save_conversation, set_user_card
from storage.user_deletion import delete_user_private_data

USER_ID = "user-card-user"
CONVERSATION_ID = "user-card-conversation"
MESSAGES = [{"role": "user", "content": "I moved to Pune last month, I work as a designer."}]


def _response(user_card: object, operations: list | None = None) -> dict:
    return {
        "decision": "propose" if operations else "no_change",
        "operations": operations or [],
        "thread_operation": {"operation": "none"},
        "handoff": {
            "summary": "",
            "active_people": [],
            "active_topics": [],
            "unresolved_references": [],
        },
        "user_card": user_card,
    }


class ValidateUserCardTest(unittest.TestCase):
    def test_cleans_lines(self) -> None:
        self.assertEqual(
            validate_user_card("  Lives in   Pune.\n\n Works as a designer. "),
            "Lives in Pune.\nWorks as a designer.",
        )

    def test_missing_or_blank_keeps_the_stored_card(self) -> None:
        for raw in (None, "", "   ", 42):
            with self.subTest(raw=raw):
                self.assertIsNone(validate_user_card(raw))

    def test_long_card_is_cut_at_a_line_end(self) -> None:
        card = validate_user_card("\n".join(f"Fact number {i}." for i in range(200)))
        self.assertLessEqual(len(card), MAX_USER_CARD_CHARS)
        self.assertTrue(card.endswith("."))

    def test_prompt_explains_the_card(self) -> None:
        self.assertIn("current_user_card", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)
        self.assertIn("If current_user_card is empty, write", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)
        self.assertIn("never a copy of the current card", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)
        self.assertIn('never write lines like "Name: not given"', BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)


class ReplacedLinesTest(unittest.TestCase):
    STUDYING = {"statement": "Is currently studying transformers in machine learning.", "value": "studying transformers in machine learning"}

    def test_line_for_a_finished_activity_goes(self) -> None:
        card = "Lives in Jaipur\nCurrently studying: transformers in machine learning"
        replaced = [(self.STUDYING, "Finished studying transformers in machine learning")]
        self.assertEqual(without_replaced_lines(card, replaced), "Lives in Jaipur")

    def test_line_that_already_says_it_ended_stays(self) -> None:
        card = "Finished studying transformers in machine learning in Oct 2026"
        replaced = [(self.STUDYING, "Finished studying transformers in machine learning")]
        self.assertEqual(without_replaced_lines(card, replaced), card)

    def test_retracted_fact_goes(self) -> None:
        old = {"statement": "Lives in Jaipur.", "value": "Jaipur"}
        self.assertEqual(without_replaced_lines("Lives in Jaipur\nWorks as a designer", [(old, None)]), "Works as a designer")


class UserCardFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": MESSAGES}, USER_ID)
        self.env = patch.dict(
            os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    async def _run(self, user_card: object, operations: list | None = None) -> AsyncMock:
        with patch(
            "agent.cognition.background.memory_run.service.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=_response(user_card, operations),
        ) as provider:
            result = await run_background_cognition(CONVERSATION_ID, USER_ID, MESSAGES)
        self.assertNotIn(result["status"], {"live_invalid", "live_error"}, result)
        return provider

    async def test_background_writes_the_card_and_sends_the_current_one(self) -> None:
        set_user_card(USER_ID, "Works as a designer.")
        provider = await self._run("Lives in Pune (moved Aug 2026).\nWorks as a designer.")

        payload = json.loads(provider.await_args.args[0])
        self.assertEqual(payload["current_user_card"], "Works as a designer.")
        self.assertEqual(get_user_card(USER_ID), "Lives in Pune (moved Aug 2026).\nWorks as a designer.")

    async def test_null_card_keeps_the_stored_one(self) -> None:
        set_user_card(USER_ID, "Works as a designer.")
        await self._run(None)
        self.assertEqual(get_user_card(USER_ID), "Works as a designer.")

    async def test_null_card_drops_the_line_of_a_replaced_memory(self) -> None:
        old = create_agent_memory(
            {
                "user_id": USER_ID,
                "kind": "semantic",
                "purposes": ["profile"],
                "key": "location.home",
                "value": "Jaipur",
                "statement": "Lives in Jaipur.",
                "confidence": 0.9,
                "importance": 0.6,
                "evidence": [{"conversation_id": CONVERSATION_ID, "message_index": 0, "exact_quote": MESSAGES[0]["content"], "observed_at": "2026-10-01T10:00:00+00:00"}],
            }
        )
        set_user_card(USER_ID, "Lives in Jaipur\nWorks as a designer.")
        await self._run(
            None,
            [
                {
                    "operation": "supersede",
                    "target_memory_id": old["id"],
                    "memory_kind": "semantic",
                    "purposes": ["profile"],
                    "key": "location.home",
                    "value": "Pune",
                    "statement": "Lives in Pune.",
                    "sensitivity": "standard",
                    "confidence": 0.9,
                    "importance": 0.6,
                    "evidence_message_indexes": [0],
                }
            ],
        )
        self.assertEqual(get_user_card(USER_ID), "Works as a designer.")

    def test_card_is_in_every_reply_context(self) -> None:
        set_user_card(USER_ID, "Lives in Pune.")
        sources = build_reply_context_sources(CONVERSATION_ID, None, "random chat", USER_ID)
        card = next(source for source in sources if source["source_type"] == "user_card")
        self.assertIn("Lives in Pune.", card["content"])

    def test_card_is_deleted_with_the_user(self) -> None:
        set_user_card(USER_ID, "Lives in Pune.")
        delete_user_private_data(USER_ID)
        self.assertIsNone(get_user_card(USER_ID))


if __name__ == "__main__":
    unittest.main()
