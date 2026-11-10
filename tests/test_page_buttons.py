"""Omi can put a button under its reply that opens an app page; on messaging apps it is a link."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from agent.context_engine.policy.replies import keep_open_marker, strip_open_marker
from agent.context_engine.prompt_engine.modules.omiryn_facts import abilities_block
from agent.providers.gateway.clients import TOOL_CALL_MARKER
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

    def test_a_rewrite_keeps_the_drafts_button(self) -> None:
        self.assertEqual(keep_open_marker("Chats are encrypted <open:privacy>", "They're encrypted."), "They're encrypted. <open:privacy>")
        # Its own button wins, and a wordless rewrite or a draft without one is left alone.
        self.assertEqual(keep_open_marker("a <open:privacy>", "b <open:memories>"), "b <open:memories>")
        self.assertEqual(keep_open_marker("a <open:privacy>", ""), "")
        self.assertEqual(keep_open_marker("just words", "other words"), "other words")

    def test_omi_is_told_about_the_button(self) -> None:
        self.assertIn("show_app_page", abilities_block())


class ShowAppPageToolTest(unittest.TestCase):
    def _run(self, page: str) -> dict:
        from agent.tools import ToolCall, ToolContext, run_calls

        result = asyncio.run(run_calls([ToolCall("show_app_page", {"page": page})], ToolContext(user_id="u1")))[0]
        return result.trace

    def test_a_known_page_is_recorded_and_an_unknown_one_is_not(self) -> None:
        from agent.tools.app_pages import shown_page

        self.assertEqual(self._run("Privacy")["page"], "privacy")
        self.assertIsNone(self._run("settings")["page"])
        self.assertEqual(shown_page([self._run("vibe"), self._run("memories")]), "memories")
        self.assertIsNone(shown_page([{"tool": "web_search", "page": "privacy"}]))

    def test_the_draft_carries_the_button_the_tool_asked_for(self) -> None:
        from agent.runtime.steps.draft import write_draft
        from agent.runtime.steps.job import ReplyJob

        replies = iter([
            TOOL_CALL_MARKER + '{"name": "show_app_page", "arguments": {"page": "privacy"}}',
            "Chats are stored encrypted.",
        ])

        async def generate(*args, **kwargs):
            return next(replies)

        job = ReplyJob(reply_messages=[{"role": "user", "content": "tell ur privacy policy"}], generation_arguments={}, generate=generate)
        with patch.dict("os.environ", {"AGENT_TOOLS": "true"}):
            draft = asyncio.run(write_draft(job))
        self.assertEqual(finish_reply(draft.reply, "tell ur privacy policy").open_page, "privacy")


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
