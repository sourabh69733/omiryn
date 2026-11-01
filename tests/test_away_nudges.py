"""Users away from the app hear from Omi on WhatsApp and Telegram: the same nudges as in the app,
only in their daytime, never to chase someone quiet for days; and a story goes on in a channel
chat without an open socket. Every agent-initiated bubble in a channel chat is sent there by the
delivery path itself."""

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import storage
from agent.context_engine.threads.models import ConversationThread
from agent.proactive.away import nudge_away, run_away_follow_ups
from agent.proactive.service import deliver_messages
from agent.proactive.story import run_story_part_job

# 14:00 in Kolkata.
NOW = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)
USER_ID = "away-user"
CHAT = "away-whatsapp-chat"
WHATSAPP_ENV = {
    "WHATSAPP_ENABLED": "true", "WHATSAPP_ACCESS_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1",
    "WHATSAPP_PHONE_NUMBER": "911", "WHATSAPP_APP_SECRET": "s", "WHATSAPP_VERIFY_TOKEN": "v",
}


def _msg(role: str, minutes_ago: float, text: str = "x", **extra) -> dict:
    return {"role": role, "content": text, "created_at": (NOW - timedelta(minutes=minutes_ago)).isoformat(), **extra}


def _thread() -> ConversationThread:
    return ConversationThread(
        id="t1", user_id=USER_ID, created_in_conversation_id=CHAT, last_conversation_id=CHAT,
        title="Riya", summary="Riya keeps calling", origin="user", next_angle="ask how it felt",
    )


class AwayNudgeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        storage.reset_db()
        storage.set_user_timezone(USER_ID, "Asia/Kolkata")
        storage.link_channel_chat(USER_ID, "whatsapp", "91999")
        self.env = patch.dict(os.environ, {"AGENT_PROVIDER": "mock", **WHATSAPP_ENV})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def _seed(self, messages: list[dict]) -> None:
        storage.save_conversation({"id": CHAT, "status": "active", "channel": "whatsapp", "messages": messages}, USER_ID)

    async def _pass(self, now: datetime = NOW, reply: str = "Riya ka phone aaya phir?") -> tuple[int, AsyncMock, AsyncMock]:
        send = AsyncMock(return_value=True)
        generate = AsyncMock(return_value=reply)
        with patch("agent.proactive.service.list_threads", return_value=[_thread()]), patch(
            "agent.proactive.service.list_agent_memories", return_value=[]
        ), patch("agent.proactive.service._generate", generate), patch("channels.whatsapp.send_whatsapp_message", send):
            sent = await run_away_follow_ups(set(), now)
        return sent, generate, send

    async def test_an_away_user_gets_a_topic_nudge_on_whatsapp(self) -> None:
        self._seed([_msg("user", 90), _msg("assistant", 89)])
        sent, generate, send = await self._pass()
        self.assertEqual(sent, 1)
        send.assert_awaited_once_with("91999", "Riya ka phone aaya phir?")
        stored = storage.get_conversation(CHAT, USER_ID)["messages"][-1]
        self.assertEqual((stored["proactive_kind"], stored["thread_id"]), ("topic_nudge", "t1"))
        # The model is told the message lands on a phone.
        self.assertIn("on their phone", generate.await_args.kwargs["instructions"])

    async def test_not_at_night_not_while_in_the_app_not_after_days_of_silence(self) -> None:
        self._seed([_msg("user", 90), _msg("assistant", 89)])
        night = datetime(2026, 9, 20, 17, 30, tzinfo=UTC)  # 23:00 in Kolkata
        self.assertEqual((await self._pass(now=night))[0], 0)
        with patch("agent.proactive.service.list_threads", return_value=[_thread()]), patch("agent.proactive.service._generate", AsyncMock(return_value="x")):
            self.assertEqual(await run_away_follow_ups({USER_ID}, NOW), 0)
        self._seed([_msg("user", 60 * 24 * 5), _msg("assistant", 60 * 24 * 5 - 1)])
        self.assertEqual((await self._pass())[0], 0)

    async def test_the_app_limits_hold_on_the_phone(self) -> None:
        # The last nudge is still unanswered: no second one.
        self._seed([_msg("user", 300), _msg("assistant", 200, proactive=True, thread_id="t1")])
        self.assertEqual((await self._pass())[0], 0)

    async def test_a_channel_that_is_off_is_skipped(self) -> None:
        self._seed([_msg("user", 90), _msg("assistant", 89)])
        with patch.dict(os.environ, {"WHATSAPP_ENABLED": "false"}):
            self.assertEqual((await self._pass())[0], 0)
        self.assertFalse(await nudge_away(USER_ID, "telegram", NOW))  # no Telegram chat

    async def test_a_story_goes_on_in_a_channel_chat(self) -> None:
        self._seed([_msg("user", 3, "tell me a story"), _msg("assistant", 2, "Once, a lighthouse.", story=True)])
        send = AsyncMock(return_value=True)
        generate = AsyncMock(return_value="The light blinked.<next_message>Mira climbed the stairs.")
        with patch("agent.proactive.story.generate_initiative_text", generate), patch("channels.whatsapp.send_whatsapp_message", send):
            self.assertTrue(await run_story_part_job({"user_id": USER_ID, "conversation_id": CHAT}))
        self.assertEqual([call.args for call in send.await_args_list], [("91999", "The light blinked."), ("91999", "Mira climbed the stairs.")])
        self.assertTrue(all(m.get("story") for m in storage.get_conversation(CHAT, USER_ID)["messages"][-2:]))

    async def test_delivery_sends_nothing_for_a_web_chat(self) -> None:
        storage.save_conversation({"id": "web", "status": "active", "messages": [_msg("user", 5)]}, USER_ID)
        send = AsyncMock(return_value=True)
        with patch("channels.whatsapp.send_whatsapp_message", send):
            self.assertTrue(await deliver_messages(USER_ID, "web", expected_count=1, new_messages=[_msg("assistant", 0, "hi")]))
        send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
