"""The friend vibe card: written by background cognition, milestones reach the open chat."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.cognition.background.prompt_v3 import BACKGROUND_COGNITION_V3_SYSTEM_PROMPT
from agent.cognition.background.service import run_background_cognition
from agent.memory_engine.memories.vibe import BASIC_AREA_IDS
from storage import get_vibe_card, reset_db, save_conversation, update_vibe_card
from storage.user_deletion import delete_user_private_data

USER_ID = "vibe-card-user"
CONVERSATION_ID = "vibe-card-conversation"
MESSAGES = [
    {"role": "user", "content": "Honestly I just want one friend who gets dark humor."},
    {"role": "assistant", "content": "Loyalty matters most in a friend, I think."},
    {"role": "user", "content": "and someone who doesn't flake, seriously"},
]


def line(text: str, *indexes: int, conversation_id: str = CONVERSATION_ID) -> dict:
    """Proof from the given messages, each said on its own day."""
    return {
        "text": text,
        "evidence": [
            {"conversation_id": conversation_id, "message_index": i, "sent_at": f"2026-09-{10 + i:02d}T10:00:00+00:00"}
            for i in indexes
        ],
    }


def _response(vibe: object) -> dict:
    return {
        "decision": "no_change",
        "operations": [],
        "thread_operation": {"operation": "none"},
        "handoff": {
            "summary": "",
            "active_people": [],
            "active_topics": [],
            "unresolved_references": [],
        },
        "vibe": vibe,
    }


class VibePromptTest(unittest.TestCase):
    def test_background_prompt_asks_for_grounded_lines_only(self) -> None:
        self.assertIn("Vibe rules", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)
        self.assertIn("never fill an area just because it is empty", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)
        self.assertIn("Most batches\n  return {}", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)
        self.assertIn("Only user\n  messages count", BACKGROUND_COGNITION_V3_SYSTEM_PROMPT)


class VibeFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_db()
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": MESSAGES}, USER_ID)
        self.env = patch.dict(
            os.environ, {"AGENT_PIPELINE_VERSION": "v3", "MEMORY_EMBEDDING_MODEL": "off"}
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    async def _run(self, vibe: object) -> tuple[AsyncMock, AsyncMock]:
        with patch(
            "agent.cognition.background.service.analyze_background_cognition",
            new_callable=AsyncMock,
            return_value=_response(vibe),
        ) as provider, patch(
            "agent.cognition.background.service.realtime_hub.publish", new_callable=AsyncMock
        ) as publish:
            result = await run_background_cognition(CONVERSATION_ID, USER_ID, MESSAGES)
        self.assertNotIn(result["status"], {"live_invalid", "live_error"}, result)
        return provider, publish

    async def test_background_sends_areas_and_current_lines_only(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Likes dark humor.", 0)})
        provider, _ = await self._run({})

        payload = json.loads(provider.await_args.args[0])
        self.assertEqual(payload["current_vibe"], {"humor": "Likes dark humor."})
        self.assertIn("friend_wish", {area["id"] for area in payload["vibe_areas"]})

    async def test_lines_keep_their_user_message_evidence_and_announce_a_milestone(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Likes dark humor.", 0)})
        _, publish = await self._run(
            {"friend_wish": {"line": "Wants one close friend who doesn't flake.", "evidence": [0, 2]}}
        )

        card = get_vibe_card(USER_ID)
        self.assertEqual(card["milestone"], "first_impressions")
        self.assertEqual(
            [item["message_index"] for item in card["areas"]["friend_wish"]["evidence"]], [0, 2]
        )
        event = publish.await_args.args[0]
        self.assertEqual(event.type, "vibe.milestone")
        self.assertEqual(event.scope_id, CONVERSATION_ID)

    async def test_companion_messages_and_unknown_indexes_are_not_evidence(self) -> None:
        _, publish = await self._run(
            {
                "values": {"line": "Thinks loyalty matters most.", "evidence": [1]},
                "deal_breakers": {"line": "Can't stand flaky friends.", "evidence": [7]},
                "humor": {"line": "Likes dark humor."},
            }
        )

        self.assertEqual(get_vibe_card(USER_ID)["areas"], {})
        publish.assert_not_awaited()

    async def test_saying_it_again_adds_evidence_and_makes_the_line_clear(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Likes dark humor.", 0)})
        await self._run({"humor": {"line": "Likes dark, deadpan humor.", "evidence": [2]}})

        humor = get_vibe_card(USER_ID)["areas"]["humor"]
        self.assertEqual(humor["text"], "Likes dark, deadpan humor.")
        self.assertEqual(len(humor["evidence"]), 2)

    async def test_empty_or_bad_vibe_keeps_the_card(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Likes dark humor.", 0)})
        for raw in (None, {}, "funny", {"zodiac": {"line": "Leo", "evidence": [0]}}, {"humor": "old shape"}):
            with self.subTest(raw=raw):
                await self._run(raw)
                self.assertEqual(get_vibe_card(USER_ID)["areas"]["humor"]["text"], "Likes dark humor.")

    def test_card_is_deleted_with_the_user(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Likes dark humor.", 0)})
        delete_user_private_data(USER_ID)
        self.assertEqual(get_vibe_card(USER_ID)["areas"], {})


class VibeApiTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        from api.main import app
        from security.auth import CurrentUser, require_user

        app.dependency_overrides[require_user] = lambda: CurrentUser(
            id=USER_ID, email="vibe@example.com", display_name="Vibe"
        )
        self.app = app
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    def test_get_lists_areas_with_strength_and_the_users_own_words(self) -> None:
        save_conversation({"id": CONVERSATION_ID, "status": "active", "messages": MESSAGES}, USER_ID)
        update_vibe_card(
            USER_ID,
            {
                **{area_id: line("Known.", 0, 2) for area_id in BASIC_AREA_IDS},
                "values": line("Said once.", 0),
            },
        )

        body = self.client.get("/api/me/vibe").json()
        areas = {area["id"]: area for area in body["areas"]}

        self.assertEqual(body["milestone"], "basics")
        self.assertEqual(body["next_milestone"], "ready_to_match")
        self.assertEqual(len(body["areas"]), body["total"])
        self.assertEqual(areas["humor"]["strength"], "clear")
        newest = areas["humor"]["evidence"][0]
        self.assertEqual(newest["quote"], "and someone who doesn't flake, seriously")
        self.assertEqual((newest["conversation_id"], newest["message_index"]), (CONVERSATION_ID, 2))
        self.assertEqual(areas["values"]["strength"], "mentioned")
        self.assertIsNone(areas["conflict"]["strength"])
        self.assertEqual(areas["conflict"]["evidence"], [])

    def test_quotes_skip_deleted_chats(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Likes dark humor.", 0, conversation_id="gone")})

        areas = {area["id"]: area for area in self.client.get("/api/me/vibe").json()["areas"]}

        self.assertEqual(areas["humor"]["evidence"], [])
        self.assertEqual(areas["humor"]["evidence_count"], 1)

    def test_user_can_remove_a_wrong_line(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Wrong.", 0), "values": line("Right.", 0)})

        body = self.client.delete("/api/me/vibe/humor").json()

        self.assertEqual(set(get_vibe_card(USER_ID)["areas"]), {"values"})
        self.assertEqual(body["known"], 1)
        self.assertEqual(self.client.delete("/api/me/vibe/zodiac").status_code, 404)


if __name__ == "__main__":
    unittest.main()
