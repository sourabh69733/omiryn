"""Vibe backfill: writes a card from past chats, only with --apply, never over an existing card."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.vibe_backfill import (
    TRANSCRIPT_CHAR_BUDGET,
    backfill_user_vibe,
    chat_transcript,
)
from agent.cognition.background.vibe_prompt import VIBE_BACKFILL_SYSTEM_PROMPT
from storage import get_vibe_card, list_conversation_user_ids, reset_db, save_conversation, update_vibe_card

USER_ID = "vibe-backfill-user"
MESSAGES = [
    {"role": "assistant", "content": "Hey, I'm Omi.", "created_at": "2026-09-20T10:00:00+00:00"},
    {"role": "user", "content": "I only laugh at deadpan jokes.", "created_at": "2026-09-20T10:01:00+00:00"},
    {"role": "assistant", "content": "Ha, fair.", "created_at": "2026-09-20T10:01:05+00:00"},
    {"role": "user", "content": "And I hate people who flake.", "created_at": "2026-09-21T09:00:00+00:00"},
]
LINES = {"humor": "Only laughs at deadpan jokes.", "deal_breakers": "Hates people who flake on plans."}


class VibeBackfillTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": "vibe-backfill-chat", "status": "active", "messages": MESSAGES}, USER_ID)

    async def _run(self, vibe: object, **kwargs) -> tuple[dict, AsyncMock]:
        with patch(
            "agent.cognition.background.vibe_backfill.analyze_vibe_backfill",
            new_callable=AsyncMock,
            return_value={"vibe": vibe},
        ) as provider:
            result = await backfill_user_vibe(USER_ID, **kwargs)
        return result, provider

    async def test_dry_run_writes_nothing(self) -> None:
        result, provider = await self._run(LINES)

        self.assertEqual(result["status"], "would_write")
        self.assertEqual(result["milestone"], "first_impressions")
        self.assertEqual(get_vibe_card(USER_ID)["areas"], {})
        payload = json.loads(provider.await_args.args[0])
        self.assertIn("user: I only laugh at deadpan jokes.", payload["chats"])
        self.assertIn("companion: Ha, fair.", payload["chats"])

    async def test_apply_writes_and_dates_the_milestone_to_the_last_chat(self) -> None:
        result, _ = await self._run(LINES, apply=True)

        card = get_vibe_card(USER_ID)
        self.assertEqual(result["status"], "written")
        self.assertEqual(card["areas"], LINES)
        self.assertEqual(card["milestone_reached_at"].strftime("%Y-%m-%d"), "2026-09-21")

    async def test_existing_card_is_skipped_unless_forced(self) -> None:
        update_vibe_card(USER_ID, {"interests": "Loves F1."})

        skipped, provider = await self._run(LINES, apply=True)
        self.assertEqual(skipped["status"], "has_card")
        provider.assert_not_awaited()

        forced, _ = await self._run(LINES, apply=True, force=True)
        self.assertEqual(forced["status"], "written")
        self.assertEqual(get_vibe_card(USER_ID)["areas"], {"interests": "Loves F1.", **LINES})

    async def test_nothing_found_and_bad_output_write_nothing(self) -> None:
        for vibe in ({}, None, "funny", {"zodiac": "Leo"}):
            with self.subTest(vibe=vibe):
                result, _ = await self._run(vibe, apply=True)
                self.assertEqual(result["status"], "nothing_found")
                self.assertEqual(get_vibe_card(USER_ID)["areas"], {})

    async def test_user_without_messages_is_not_sent_to_the_model(self) -> None:
        save_conversation({"id": "empty-chat", "status": "active", "messages": []}, "quiet-user")
        with patch(
            "agent.cognition.background.vibe_backfill.analyze_vibe_backfill", new_callable=AsyncMock
        ) as provider:
            result = await backfill_user_vibe("quiet-user", apply=True)
        self.assertEqual(result["status"], "no_messages")
        provider.assert_not_awaited()

    def test_lists_users_with_chats(self) -> None:
        self.assertIn(USER_ID, list_conversation_user_ids())


class ChatTranscriptTest(unittest.TestCase):
    def test_long_history_keeps_the_most_recent_text(self) -> None:
        old = [{"role": "user", "content": f"old message {i} " + "x" * 500} for i in range(80)]
        recent = [{"role": "user", "content": "the newest thing I said"}]
        transcript, _ = chat_transcript([{"id": "c1", "messages": old + recent}])

        self.assertLessEqual(len(transcript), TRANSCRIPT_CHAR_BUDGET)
        self.assertTrue(transcript.endswith("the newest thing I said"))
        self.assertNotIn("old message 0 ", transcript)

    def test_failed_messages_and_companion_only_chats_are_skipped(self) -> None:
        transcript, _ = chat_transcript(
            [{"id": "c1", "messages": [{"role": "user", "content": "lost", "delivery_status": "failed"},
                                       {"role": "assistant", "content": "Hi!"}]}]
        )
        self.assertEqual(transcript, "")

    def test_prompt_shares_the_grounding_rules(self) -> None:
        self.assertIn("never fill an area just because it is empty", VIBE_BACKFILL_SYSTEM_PROMPT)
        self.assertIn("returning {} is fine", VIBE_BACKFILL_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
