"""A rewritten vibe line is re-proven; deleted chats and unfit proof leave the card."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from agent.cognition.background.service import run_background_cognition
from agent.cognition.background.vibe_backfill import recheck_user_vibe
from agent.memory_engine.memories.vibe import merge_vibe, with_current_proof
from storage import delete_conversation, get_vibe_card, reset_db, save_conversation, update_vibe_card

USER = "reprove-user"
OLD_CHAT, NEW_CHAT = "old-chat", "new-chat"
OLD_MESSAGES = [
    {"role": "user", "content": "I ride my bike every evening", "created_at": "2026-09-20T18:00:00+00:00"},
    {"role": "assistant", "content": "Nice!", "created_at": "2026-09-20T18:00:05+00:00"},
]
NEW_MESSAGES = [
    {"role": "user", "content": "i love harry potter movies", "created_at": "2026-10-04T11:08:00+00:00"},
    {"role": "assistant", "content": "Which one?", "created_at": "2026-10-04T11:08:05+00:00"},
    {"role": "user", "content": "the last 2 are amazing", "created_at": "2026-10-04T11:09:00+00:00"},
]


def proof(chat: str, index: int, sent_at: str) -> dict:
    return {"conversation_id": chat, "message_index": index, "sent_at": sent_at}


BIKE_PROOF = proof(OLD_CHAT, 0, "2026-09-20T18:00:00+00:00")


class MergeTest(unittest.TestCase):
    def test_replace_evidence_drops_proof_for_what_the_line_used_to_say(self) -> None:
        card = {"interests": {"text": "Rides a bike.", "evidence": [BIKE_PROOF]}}
        update = {"interests": {"text": "Loves Harry Potter.", "evidence": [proof(NEW_CHAT, 0, "2026-10-04T11:08:00+00:00")]}}

        self.assertEqual(len(merge_vibe(card, update)["interests"]["evidence"]), 2)
        replaced = merge_vibe(card, update, replace_evidence=True)
        self.assertEqual([item["conversation_id"] for item in replaced["interests"]["evidence"]], [NEW_CHAT])

    def test_the_proof_check_sees_old_and_new_proof_together(self) -> None:
        card = {"interests": {"text": "Rides a bike.", "evidence": [BIKE_PROOF]}}
        update = {"interests": {"text": "Loves Harry Potter.", "evidence": [proof(NEW_CHAT, 0, "x")]}}

        combined = with_current_proof(update, card)["interests"]
        self.assertEqual(combined["text"], "Loves Harry Potter.")
        self.assertEqual(len(combined["evidence"]), 2)


class ReproveFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": OLD_CHAT, "status": "active", "messages": OLD_MESSAGES}, USER)
        save_conversation({"id": NEW_CHAT, "status": "active", "messages": NEW_MESSAGES}, USER)
        update_vibe_card(USER, {"interests": {"text": "Rides a bike every evening.", "evidence": [BIKE_PROOF]}})
        self.env = patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    async def test_a_rewrite_keeps_only_proof_that_shows_the_new_text(self) -> None:
        response = {
            "decision": "no_change",
            "operations": [],
            "thread_operation": {"operation": "none"},
            "handoff": {"summary": "", "active_people": [], "active_topics": [], "unresolved_references": []},
            "vibe": {"interests": {"line": "Loves Harry Potter, especially the last two.", "evidence": [0, 2]}},
        }

        async def checker(text, **_kwargs):
            import json
            payload = json.loads(text)
            # Keep only the Harry Potter messages; the old bike message does not show the new text.
            return {
                line["area"]: [m["id"] for m in line["messages"] if "bike" not in m["text"]]
                for line in payload["lines"]
            }

        with patch(
            "agent.cognition.background.service.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=response,
        ), patch("agent.cognition.background.vibe_verify.analyze_vibe_verification", side_effect=checker), patch(
            "agent.cognition.background.service.realtime_hub.publish", new_callable=AsyncMock
        ):
            await run_background_cognition(NEW_CHAT, USER, NEW_MESSAGES)

        line = get_vibe_card(USER)["areas"]["interests"]
        self.assertEqual(line["text"], "Loves Harry Potter, especially the last two.")
        self.assertEqual({item["conversation_id"] for item in line["evidence"]}, {NEW_CHAT})
        self.assertEqual(len(line["evidence"]), 2)

    def test_deleting_a_chat_takes_its_proof_and_lines_left_without_proof(self) -> None:
        update_vibe_card(
            USER,
            {"humor": {"text": "Likes dry jokes.", "evidence": [proof(NEW_CHAT, 0, "2026-10-04T11:08:00+00:00")]}},
        )

        delete_conversation(OLD_CHAT, USER)

        areas = get_vibe_card(USER)["areas"]
        self.assertNotIn("interests", areas)
        self.assertIn("humor", areas)

    async def test_recheck_drops_unreadable_and_unfit_proof(self) -> None:
        update_vibe_card(
            USER,
            {
                "humor": {"text": "Likes dry jokes.", "evidence": [proof("deleted-chat", 0, "2026-09-01T10:00:00+00:00")]},
                "values": {"text": "Values honesty.", "evidence": [proof(NEW_CHAT, 0, "2026-10-04T11:08:00+00:00")]},
            },
        )
        with patch(
            "agent.cognition.background.vibe_verify.analyze_vibe_verification",
            new_callable=AsyncMock,
            return_value={"interests": ["e1"], "values": []},
        ):
            dry = await recheck_user_vibe(USER)
            self.assertEqual(dry["status"], "would_recheck")
            self.assertEqual(set(get_vibe_card(USER)["areas"]), {"interests", "humor", "values"})
            result = await recheck_user_vibe(USER, apply=True)

        self.assertEqual(result["status"], "rechecked")
        self.assertEqual(result["dropped"], ["humor", "values"])
        self.assertEqual(set(get_vibe_card(USER)["areas"]), {"interests"})


if __name__ == "__main__":
    unittest.main()
