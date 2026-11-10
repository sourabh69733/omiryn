"""Omi can put a button under its reply that opens an app page; on messaging apps it is a link."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.policy.replies import strip_open_marker
from agent.context_engine.prompt_engine.modules.omiryn_facts import abilities_block
from agent.runtime.steps import assistant_messages, finish_reply
from api.routes import channel_replies
from api.routes.channel_replies import ChannelSender


class PageMarkerTest(unittest.TestCase):
    def test_the_marker_is_hidden_and_lands_on_the_last_bubble(self) -> None:
        finished = finish_reply("Chats are encrypted. <next_message> Here's how it works <open:privacy>", "is it safe")
        self.assertEqual(finished.parts, ["Chats are encrypted.", "Here's how it works"])
        messages = assistant_messages(finished, {})
        self.assertNotIn("open_page", messages[0])
        self.assertEqual(messages[-1]["open_page"], "privacy")

    def test_only_app_pages_count(self) -> None:
        self.assertEqual(strip_open_marker("see <open:settings>"), ("see", None))
        self.assertEqual(strip_open_marker("see [open: Memories]"), ("see", "memories"))
        self.assertIsNone(finish_reply("just words", "hi").open_page)

    def test_a_wordless_reply_gets_no_button(self) -> None:
        finished = finish_reply("<react:👍> <open:vibe>", "ok")
        self.assertEqual(assistant_messages(finished, {}), [])

    def test_omi_is_told_about_the_button(self) -> None:
        self.assertIn("<open:privacy>", abilities_block())


class ChannelLinkTest(unittest.TestCase):
    def _send(self, replies: list[dict]) -> list[str]:
        sender = ChannelSender("telegram", AsyncMock(), AsyncMock(), AsyncMock(return_value=True), 4.0)
        with patch.object(channel_replies, "BUBBLE_PAUSE_SECONDS", 0), patch.object(channel_replies, "WEB_APP_URL", "https://app.example.com"):
            asyncio.run(channel_replies._send_bubbles(sender, "42", replies))
        return [call.args[1] for call in sender.send_text.await_args_list]

    def test_the_page_is_a_link_under_the_last_bubble(self) -> None:
        sent = self._send([
            {"role": "assistant", "content": "Chats are encrypted."},
            {"role": "assistant", "content": "Here's how it works", "open_page": "privacy"},
        ])
        self.assertEqual(sent, ["Chats are encrypted.", "Here's how it works\nhttps://app.example.com/profile/privacy"])

    def test_no_page_no_link(self) -> None:
        self.assertEqual(self._send([{"role": "assistant", "content": "hey"}]), ["hey"])


if __name__ == "__main__":
    unittest.main()
