"""The profile intro: written by the model from non-private vibe lines, cached until they change."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from storage import get_vibe_card, reset_db, save_conversation, update_vibe_card

USER_ID = "intro-user"


def line(text: str) -> dict:
    return {"text": text, "evidence": [{"conversation_id": "c1", "message_index": 0, "sent_at": "2026-09-10T10:00:00+00:00"}]}


class VibeIntroApiTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        from api.main import app
        from security.auth import CurrentUser, require_user

        app.dependency_overrides[require_user] = lambda: CurrentUser(
            id=USER_ID, email="intro@example.com", display_name="Riya Sen"
        )
        self.app = app
        self.client = TestClient(app)
        save_conversation({"id": "c1", "status": "active", "messages": [{"role": "user", "content": "hi"}]}, USER_ID)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    def _get(self, writer: AsyncMock) -> dict:
        with patch("api.routes.vibe.write_vibe_intro", writer):
            return self.client.get("/api/me/intro").json()

    def test_not_ready_with_too_few_non_private_lines(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Laughs at puns."), "values": line("Believes in honesty.")})
        writer = AsyncMock()

        body = self._get(writer)

        self.assertEqual(body, {"intro": None, "chips": [], "ready": False})
        writer.assert_not_called()

    def test_written_from_non_private_lines_only_and_cached(self) -> None:
        update_vibe_card(
            USER_ID,
            {"humor": line("Laughs at puns."), "interests": line("Builds at hackathons."), "values": line("Prays daily.")},
        )
        writer = AsyncMock(return_value={"intro": "Builds at 2 am and laughs at puns.", "chips": ["Hackathons", "Puns", ""]})

        first = self._get(writer)
        second = self._get(writer)

        self.assertEqual(first, {"intro": "Builds at 2 am and laughs at puns.", "chips": ["Hackathons", "Puns"], "ready": True})
        self.assertEqual(second, first)
        writer.assert_awaited_once()
        sent = json.loads(writer.await_args.args[0])
        self.assertEqual(sent["first_name"], "Riya")
        self.assertEqual(set(sent["vibe_lines"]), {"humor", "interests"})

    def test_rewritten_when_lines_change_and_kept_when_writing_fails(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Laughs at puns."), "interests": line("Builds at hackathons.")})
        self._get(AsyncMock(return_value={"intro": "First intro.", "chips": []}))

        update_vibe_card(USER_ID, {"daily_life": line("Codes late at night.")})
        failed = self._get(AsyncMock(side_effect=TimeoutError()))
        self.assertEqual(failed["intro"], "First intro.")

        rewritten = self._get(AsyncMock(return_value={"intro": "Second intro.", "chips": ["Late nights"]}))
        self.assertEqual(rewritten["intro"], "Second intro.")

    def test_vibe_updates_keep_the_saved_intro(self) -> None:
        update_vibe_card(USER_ID, {"humor": line("Laughs at puns."), "interests": line("Builds at hackathons.")})
        self._get(AsyncMock(return_value={"intro": "Saved intro.", "chips": []}))

        update_vibe_card(USER_ID, {}, reject=("humor",))

        self.assertEqual(get_vibe_card(USER_ID)["intro"]["text"], "Saved intro.")


if __name__ == "__main__":
    unittest.main()
