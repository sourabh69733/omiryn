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
MESSAGES = [{"role": "user", "content": "Honestly I just want one friend who gets dark humor."}]


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

    async def test_background_sends_areas_and_current_card(self) -> None:
        update_vibe_card(USER_ID, {"humor": "Likes dark humor."})
        provider, _ = await self._run({})

        payload = json.loads(provider.await_args.args[0])
        self.assertEqual(payload["current_vibe"], {"humor": "Likes dark humor."})
        self.assertIn("friend_wish", {area["id"] for area in payload["vibe_areas"]})

    async def test_new_lines_are_saved_and_a_milestone_is_announced(self) -> None:
        update_vibe_card(USER_ID, {"humor": "Likes dark humor."})
        _, publish = await self._run({"friend_wish": "Wants one close friend who gets dark humor."})

        self.assertEqual(get_vibe_card(USER_ID)["milestone"], "first_impressions")
        event = publish.await_args.args[0]
        self.assertEqual(event.type, "vibe.milestone")
        self.assertEqual(event.scope_id, CONVERSATION_ID)
        self.assertEqual(event.payload["milestone"], "first_impressions")

    async def test_no_event_when_the_milestone_holds(self) -> None:
        _, publish = await self._run({"humor": "Likes dark humor."})

        self.assertEqual(get_vibe_card(USER_ID)["areas"], {"humor": "Likes dark humor."})
        publish.assert_not_awaited()

    async def test_empty_or_bad_vibe_keeps_the_card(self) -> None:
        update_vibe_card(USER_ID, {"humor": "Likes dark humor."})
        for raw in (None, {}, "funny", {"zodiac": "Leo"}):
            with self.subTest(raw=raw):
                await self._run(raw)
                self.assertEqual(get_vibe_card(USER_ID)["areas"], {"humor": "Likes dark humor."})

    def test_card_is_deleted_with_the_user(self) -> None:
        update_vibe_card(USER_ID, {"humor": "Likes dark humor."})
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

    def test_get_lists_every_area_with_progress(self) -> None:
        update_vibe_card(USER_ID, {area_id: "Known." for area_id in BASIC_AREA_IDS})

        body = self.client.get("/api/me/vibe").json()

        self.assertEqual(body["milestone"], "basics")
        self.assertEqual(body["next_milestone"], "ready_to_match")
        self.assertEqual(body["known"], len(BASIC_AREA_IDS))
        self.assertEqual(len(body["areas"]), body["total"])
        self.assertIsNotNone(body["milestone_reached_at"])

    def test_user_can_remove_a_wrong_line(self) -> None:
        update_vibe_card(USER_ID, {"humor": "Wrong.", "values": "Right."})

        body = self.client.delete("/api/me/vibe/humor").json()

        self.assertEqual(get_vibe_card(USER_ID)["areas"], {"values": "Right."})
        self.assertEqual(body["known"], 1)
        self.assertEqual(self.client.delete("/api/me/vibe/zodiac").status_code, 404)


if __name__ == "__main__":
    unittest.main()
