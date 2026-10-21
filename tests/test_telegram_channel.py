"""Chat with Omi on Telegram: connect with a one-time code, then messages reach the Omi chat."""

import os
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agent.shared.clock import utc_now
from api.main import app, current_user
from api.routes import telegram as telegram_routes
from security.auth import CurrentUser
from storage import (
    channel_link_for_user,
    create_channel_link_code,
    delete_user_private_data,
    list_conversations,
    reset_db,
)
from storage.database import ENGINE
from storage.schema import channel_link_codes

USER_ID = "telegram-user"
EMAIL = "tester@example.com"
CHAT_ID = 555001
SECRET = "webhook-secret"


class TelegramChannelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "AUTH_REQUIRED": "false",
                "AGENT_PROVIDER": "mock",
                "DATA_POINT_EXTRACTOR": "rules",
                "AGENT_PIPELINE_VERSION": "v1",
                "AGENT_ROLLOUT": "off",
                "TELEGRAM_ENABLED": "true",
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_BOT_USERNAME": "OmirynTestBot",
                "TELEGRAM_WEBHOOK_SECRET": SECRET,
                "TELEGRAM_ALLOWED_EMAILS": "",
            },
        )
        self.env.start()
        app.dependency_overrides.clear()

        async def signed_in_user() -> CurrentUser:
            return CurrentUser(id=USER_ID, email=EMAIL, display_name="Tester")

        app.dependency_overrides[current_user] = signed_in_user
        reset_db()
        self.client = TestClient(app)
        self.sent = AsyncMock(return_value=True)
        self.patches = [
            patch.object(telegram_routes, "send_telegram_message", self.sent),
            patch.object(telegram_routes, "send_telegram_typing", AsyncMock()),
            patch.object(telegram_routes, "_BUBBLE_PAUSE_SECONDS", 0),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        app.dependency_overrides.clear()
        self.env.stop()

    def _webhook(self, text: str | None, update_id: int = 1, chat_type: str = "private", secret: str = SECRET):
        message: dict = {"message_id": update_id, "chat": {"id": CHAT_ID, "type": chat_type}}
        if text is not None:
            message["text"] = text
        return self.client.post(
            "/api/channels/telegram/webhook",
            json={"update_id": update_id, "message": message},
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        )

    def _connect(self) -> None:
        url = self.client.post("/api/channels/telegram/link").json()["url"]
        code = url.split("?start=", 1)[1]
        self.assertEqual(self._webhook(f"/start {code}", update_id=1).status_code, 200)

    def _sent_texts(self) -> list[str]:
        return [call.args[1] for call in self.sent.await_args_list]

    def _omi_chat(self) -> dict:
        return next(row for row in list_conversations(USER_ID) if not row["temporary"])

    def test_link_points_to_the_bot_with_a_one_time_code(self) -> None:
        response = self.client.post("/api/channels/telegram/link")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["url"].startswith("https://t.me/OmirynTestBot?start="))

    def test_start_with_the_code_connects_the_chat(self) -> None:
        self.assertFalse(self.client.get("/api/channels/telegram").json()["connected"])

        self._connect()

        status = self.client.get("/api/channels/telegram").json()
        self.assertTrue(status["available"])
        self.assertTrue(status["connected"])
        self.assertEqual(channel_link_for_user(USER_ID, "telegram")["external_chat_id"], str(CHAT_ID))
        self.assertIn(telegram_routes._LINKED, self._sent_texts())

    def test_a_code_works_only_once(self) -> None:
        code = self.client.post("/api/channels/telegram/link").json()["url"].split("?start=", 1)[1]
        self._webhook(f"/start {code}", update_id=1)
        self.client.delete("/api/channels/telegram")

        self._webhook(f"/start {code}", update_id=2)

        self.assertIsNone(channel_link_for_user(USER_ID, "telegram"))
        self.assertEqual(self._sent_texts()[-1], telegram_routes._EXPIRED)

    def test_an_expired_code_does_not_connect(self) -> None:
        code, _ = create_channel_link_code(USER_ID, "telegram")
        with ENGINE.begin() as connection:
            connection.execute(channel_link_codes.update().values(expires_at=utc_now() - timedelta(minutes=1)))

        self._webhook(f"/start {code}")

        self.assertIsNone(channel_link_for_user(USER_ID, "telegram"))
        self.assertEqual(self._sent_texts()[-1], telegram_routes._EXPIRED)

    def test_wrong_secret_is_rejected(self) -> None:
        self.assertEqual(self._webhook("hi", secret="nope").status_code, 401)
        self.sent.assert_not_awaited()

    def test_webhook_is_off_when_telegram_is_disabled(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_ENABLED": "false"}):
            self.assertEqual(self._webhook("hi").status_code, 404)
            self.assertFalse(self.client.get("/api/channels/telegram").json()["available"])

    def test_an_unconnected_chat_is_told_how_to_connect(self) -> None:
        self._webhook("hello")

        self.assertEqual(self._sent_texts(), [telegram_routes._CONNECT_HINT])
        self.assertEqual(list_conversations(USER_ID), [])

    def test_a_message_goes_to_the_omi_chat_and_the_reply_comes_back(self) -> None:
        self._connect()
        web_chat_id = self.client.post("/api/agent/conversations").json()["id"]
        self.sent.reset_mock()

        response = self._webhook("hey, I just moved to Pune", update_id=2)

        self.assertEqual(response.status_code, 200)
        chat = self._omi_chat()
        self.assertEqual(chat["id"], web_chat_id)
        user_message = chat["messages"][1]
        self.assertEqual(user_message["content"], "hey, I just moved to Pune")
        self.assertEqual(user_message["channel"], "telegram")
        self.assertEqual(user_message["delivery_status"], "read")
        replies = [message["content"] for message in chat["messages"][2:] if message["role"] == "assistant"]
        self.assertTrue(replies)
        self.assertEqual(self._sent_texts(), replies)

    def test_typing_shows_before_omi_starts_writing(self) -> None:
        self._connect()
        order: list[str] = []
        typing = AsyncMock(side_effect=lambda chat_id: order.append("typing"))

        async def turn(**kwargs):
            order.append("turn")
            raise RuntimeError("stop here")

        with patch.object(telegram_routes, "send_telegram_typing", typing), patch("api.main.run_agent_turn", turn):
            self._webhook("hi", update_id=2)

        self.assertEqual(order[:2], ["typing", "turn"])

    def test_a_first_message_starts_the_omi_chat_when_there_is_none(self) -> None:
        self._connect()

        self._webhook("hi", update_id=2)

        self.assertEqual(len(list_conversations(USER_ID)), 1)
        self.assertEqual(self._omi_chat()["messages"][1]["content"], "hi")

    def test_a_retried_delivery_is_answered_once(self) -> None:
        self._connect()

        self._webhook("hi", update_id=2)
        self._webhook("hi", update_id=2)

        user_messages = [m for m in self._omi_chat()["messages"] if m["role"] == "user"]
        self.assertEqual(len(user_messages), 1)

    def test_a_failed_reply_is_told_in_the_chat(self) -> None:
        self._connect()
        self.sent.reset_mock()

        with patch("api.main.run_agent_turn", AsyncMock(side_effect=RuntimeError("model down"))):
            response = self._webhook("hi", update_id=2)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._sent_texts(), [telegram_routes._REPLY_FAILED])
        self.assertEqual(self._omi_chat()["messages"][1]["delivery_status"], "failed")

    def test_non_text_messages_get_a_short_note(self) -> None:
        self._connect()
        self.sent.reset_mock()

        self._webhook(None, update_id=2)

        self.assertEqual(self._sent_texts(), [telegram_routes._TEXT_ONLY])

    def test_group_chats_are_ignored(self) -> None:
        self._webhook("hi", chat_type="group")

        self.sent.assert_not_awaited()

    def test_disconnect_from_telegram(self) -> None:
        self._connect()

        self._webhook("/disconnect", update_id=2)

        self.assertIsNone(channel_link_for_user(USER_ID, "telegram"))
        self.assertEqual(self._sent_texts()[-1], telegram_routes._DISCONNECTED)

    def test_disconnect_from_profile_says_goodbye_in_telegram(self) -> None:
        self._connect()

        response = self.client.delete("/api/channels/telegram")

        self.assertFalse(response.json()["connected"])
        self.assertIsNone(channel_link_for_user(USER_ID, "telegram"))
        self.assertEqual(self.sent.await_args.args, (str(CHAT_ID), telegram_routes._DISCONNECTED))

    def test_only_allowed_testers_can_connect(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_EMAILS": "someone@else.com"}):
            self.assertFalse(self.client.get("/api/channels/telegram").json()["available"])
            self.assertEqual(self.client.post("/api/channels/telegram/link").status_code, 403)
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_EMAILS": "someone@else.com, Tester@Example.com"}):
            self.assertEqual(self.client.post("/api/channels/telegram/link").status_code, 200)

    def test_account_deletion_removes_the_link(self) -> None:
        self._connect()
        self.client.post("/api/channels/telegram/link")

        deleted = delete_user_private_data(USER_ID)["deleted"]

        self.assertEqual(deleted["channel_links"], 1)
        self.assertEqual(deleted["channel_link_codes"], 1)
        self.assertIsNone(channel_link_for_user(USER_ID, "telegram"))


if __name__ == "__main__":
    unittest.main()
