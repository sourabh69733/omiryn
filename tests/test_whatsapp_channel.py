"""Chat with Omi on WhatsApp: connect with a one-time code, then Omi replies in its own chat."""

import asyncio
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import unquote

import httpx
from fastapi.testclient import TestClient

from agent.runtime.orchestrator import AgentTurnResult
from api.main import app, current_user
from api.routes import channel_replies
from api.routes import whatsapp as whatsapp_routes
from security.auth import CurrentUser
from storage import channel_link_for_user, list_conversations, reset_db

USER_ID = "whatsapp-user"
EMAIL = "tester@example.com"
WA_ID = "919800000001"
APP_SECRET = "app-secret"
VERIFY_TOKEN = "verify-me"


class _FakeTurn:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kwargs) -> AgentTurnResult:
        self.calls.append(kwargs)
        user_message = {"role": "user", "content": kwargs["user_text"]}
        reply = {"role": "assistant", "content": f"reply {len(self.calls)}"}
        return AgentTurnResult(messages=[*kwargs["messages"], user_message, reply], quality_valid=True)


class WhatsAppChannelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "AUTH_REQUIRED": "false",
                "AGENT_PROVIDER": "mock",
                "DATA_POINT_EXTRACTOR": "rules",
                "AGENT_PIPELINE_VERSION": "v1",
                "AGENT_ROLLOUT": "off",
                "WHATSAPP_ENABLED": "true",
                "WHATSAPP_ACCESS_TOKEN": "test-token",
                "WHATSAPP_PHONE_NUMBER_ID": "123",
                "WHATSAPP_PHONE_NUMBER": "+1 (555) 159-1227",
                "WHATSAPP_APP_SECRET": APP_SECRET,
                "WHATSAPP_VERIFY_TOKEN": VERIFY_TOKEN,
                "WHATSAPP_ALLOWED_EMAILS": "",
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
        self.typing = AsyncMock()
        self.patches = [
            patch.object(whatsapp_routes, "send_whatsapp_message", self.sent),
            patch.object(whatsapp_routes, "send_whatsapp_typing", self.typing),
            patch.object(channel_replies, "BUBBLE_PAUSE_SECONDS", 0),
            patch.object(channel_replies, "QUIET_SECONDS", 0),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        app.dependency_overrides.clear()
        self.env.stop()

    def _body(self, text: str | None, message_id: str, kind: str = "text") -> bytes:
        message: dict = {"from": WA_ID, "id": message_id, "timestamp": "1761600000", "type": kind}
        if text is not None:
            message["text"] = {"body": text}
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"id": "1", "changes": [{"field": "messages", "value": {"messaging_product": "whatsapp", "messages": [message]}}]}],
        }
        return json.dumps(payload).encode()

    @staticmethod
    def _signature(body: bytes, secret: str = APP_SECRET) -> str:
        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    async def _deliver(self, items: list[tuple[str | None, str]], gap: float = 0.0, kind: str = "text") -> list[int]:
        """Post webhook bodies (text, message_id) like Meta does, then wait for the replies."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            statuses = []
            for index, (text, message_id) in enumerate(items):
                if index:
                    await asyncio.sleep(gap)
                body = self._body(text, message_id, kind)
                response = await client.post(
                    "/api/channels/whatsapp/webhook",
                    content=body,
                    headers={"Content-Type": "application/json", "X-Hub-Signature-256": self._signature(body)},
                )
                statuses.append(response.status_code)
            while whatsapp_routes._pending:
                await asyncio.gather(*list(whatsapp_routes._pending))
        return statuses

    def _send(self, text: str | None, message_id: str = "wamid.1", kind: str = "text") -> None:
        asyncio.run(self._deliver([(text, message_id)], kind=kind))

    def _connect(self) -> None:
        url = self.client.post("/api/channels/whatsapp/link").json()["url"]
        typed = unquote(url.split("?text=", 1)[1])
        self._send(typed, "wamid.connect")

    def _sent_texts(self) -> list[str]:
        return [call.args[1] for call in self.sent.await_args_list]

    def _chat(self) -> dict:
        return next(row for row in list_conversations(USER_ID) if row["channel"] == "whatsapp")

    def test_meta_verifies_the_webhook_with_the_verify_token(self) -> None:
        query = {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1234"}
        response = self.client.get("/api/channels/whatsapp/webhook", params=query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "1234")

        wrong = self.client.get("/api/channels/whatsapp/webhook", params={**query, "hub.verify_token": "nope"})
        self.assertEqual(wrong.status_code, 403)

    def test_unsigned_or_wrongly_signed_bodies_are_rejected(self) -> None:
        body = self._body("hi", "wamid.x")
        unsigned = self.client.post("/api/channels/whatsapp/webhook", content=body)
        wrong = self.client.post(
            "/api/channels/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": self._signature(body, "other")}
        )

        self.assertEqual(unsigned.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.sent.assert_not_awaited()

    def test_link_opens_whatsapp_with_the_connect_message_typed(self) -> None:
        url = self.client.post("/api/channels/whatsapp/link").json()["url"]

        self.assertTrue(url.startswith("https://wa.me/15551591227?text=connect%20"))

    def test_sending_the_code_connects_the_chat(self) -> None:
        self._connect()

        self.assertEqual(channel_link_for_user(USER_ID, "whatsapp")["external_chat_id"], WA_ID)
        self.assertEqual(self._sent_texts(), [whatsapp_routes._LINKED])
        self.assertTrue(self.client.get("/api/channels/whatsapp").json()["connected"])

    def test_a_wrong_code_does_not_connect(self) -> None:
        self._send("connect not-a-real-code")

        self.assertIsNone(channel_link_for_user(USER_ID, "whatsapp"))
        self.assertEqual(self._sent_texts(), [whatsapp_routes._EXPIRED])

    def test_an_unconnected_number_is_told_how_to_connect(self) -> None:
        self._send("hello")

        self.assertEqual(self._sent_texts(), [whatsapp_routes._CONNECT_HINT])
        self.assertEqual(list_conversations(USER_ID), [])

    def test_a_message_gets_a_reply_in_its_own_chat(self) -> None:
        self._connect()
        web_chat = self.client.post("/api/agent/conversations").json()
        self.sent.reset_mock()

        with patch("api.main.run_agent_turn", _FakeTurn()):
            self._send("hey, I just moved to Pune", "wamid.2")

        chat = self._chat()
        self.assertNotEqual(chat["id"], web_chat["id"])
        self.assertEqual([m["content"] for m in chat["messages"]], ["hey, I just moved to Pune", "reply 1"])
        self.assertEqual(chat["messages"][0]["channel"], "whatsapp")
        self.assertEqual(self._sent_texts(), ["reply 1"])
        self.typing.assert_awaited_with("wamid.2")
        listed = [row["id"] for row in self.client.get("/api/agent/conversations").json()["conversations"]]
        self.assertEqual(listed, [web_chat["id"]])

    def test_quick_messages_get_one_reply(self) -> None:
        self._connect()
        self.sent.reset_mock()
        turn = _FakeTurn()

        with patch.object(channel_replies, "QUIET_SECONDS", 0.2), patch("api.main.run_agent_turn", turn):
            asyncio.run(self._deliver([("hey", "wamid.a"), ("listen", "wamid.b"), ("I got the job!", "wamid.c")], gap=0.02))

        self.assertEqual(len(turn.calls), 1)
        self.assertEqual(turn.calls[0]["unanswered_count"], 3)
        self.assertEqual(self._sent_texts(), ["reply 1"])

    def test_a_repeated_delivery_is_answered_once(self) -> None:
        self._connect()
        turn = _FakeTurn()

        with patch("api.main.run_agent_turn", turn):
            asyncio.run(self._deliver([("hi", "wamid.same"), ("hi", "wamid.same")]))

        self.assertEqual(len(turn.calls), 1)

    def test_non_text_messages_get_a_short_note(self) -> None:
        self._connect()
        self.sent.reset_mock()

        self._send(None, "wamid.img", kind="image")

        self.assertEqual(self._sent_texts(), [whatsapp_routes._TEXT_ONLY])

    def test_disconnect_by_message_and_from_profile(self) -> None:
        self._connect()
        self._send("Disconnect", "wamid.bye")
        self.assertIsNone(channel_link_for_user(USER_ID, "whatsapp"))
        self.assertEqual(self._sent_texts()[-1], whatsapp_routes._DISCONNECTED)

        self._connect()
        self.assertFalse(self.client.delete("/api/channels/whatsapp").json()["connected"])
        self.assertIsNone(channel_link_for_user(USER_ID, "whatsapp"))

    def test_only_allowed_testers_can_connect(self) -> None:
        with patch.dict(os.environ, {"WHATSAPP_ALLOWED_EMAILS": "someone@else.com"}):
            self.assertFalse(self.client.get("/api/channels/whatsapp").json()["available"])
            self.assertEqual(self.client.post("/api/channels/whatsapp/link").status_code, 403)

    def test_off_when_whatsapp_is_disabled(self) -> None:
        with patch.dict(os.environ, {"WHATSAPP_ENABLED": "false"}):
            self.assertEqual(self.client.post("/api/channels/whatsapp/webhook", content=b"{}").status_code, 404)
            self.assertFalse(self.client.get("/api/channels/whatsapp").json()["available"])


if __name__ == "__main__":
    unittest.main()
