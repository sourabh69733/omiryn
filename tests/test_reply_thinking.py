"""A model's private thinking never reaches the user, whichever model wrote the reply.

Seen in a real chat: the reply opened with "<think>The user asks for advice..." and listed the
rules the model was following, in the bubbles the user reads."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent.context_engine.policy.replies import without_thinking
from agent.providers.gateway.claude_chat import claude_chat
from agent.providers.shared.errors import AgentProviderError
from agent.providers.shared.messages import _compact_chat_reply

ASKED = [{"role": "user", "content": "my friend cannot move on, what can be done?"}]


def claude_answer(*texts: str):
    blocks = [SimpleNamespace(type="text", text=value) for value in texts]
    answer = SimpleNamespace(model="claude-sonnet-5-5", stop_reason="end_turn", content=blocks, usage=SimpleNamespace(input_tokens=8000, output_tokens=400))
    return SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=answer)), close=AsyncMock())


class WithoutThinkingTest(unittest.TestCase):
    def test_a_closed_block_is_cut_and_the_reply_stays(self) -> None:
        self.assertEqual(without_thinking("<think>Reply in Hinglish. One question.</think>yaar, ye bhaari hai.").strip(), "yaar, ye bhaari hai.")
        self.assertEqual(without_thinking("<Thinking>\nplan\n</Thinking>\nhaan<next_message>aur batao").strip(), "haan<next_message>aur batao")

    def test_with_only_a_closing_tag_everything_before_it_is_thinking(self) -> None:
        self.assertEqual(without_thinking("Be warm. Don't joke.</think>yaar, ye bhaari hai.").strip(), "yaar, ye bhaari hai.")

    def test_with_only_an_opening_tag_the_two_cannot_be_told_apart(self) -> None:
        self.assertIsNone(without_thinking("<think>Be warm. Ask one question.yaar, ye bhaari hai."))

    def test_a_normal_reply_is_left_alone(self) -> None:
        for reply in ("I think you should rest.", "socho mat<next_message>so jao", "what do you think? <3"):
            self.assertEqual(without_thinking(reply), reply)


class ReplyCleaningTest(unittest.TestCase):
    def test_every_reply_loses_its_thinking_before_the_user_sees_it(self) -> None:
        self.assertEqual(_compact_chat_reply("<think>Reply in Hinglish.</think>\nyaar, ye bhaari hai.", ASKED), "yaar, ye bhaari hai.")

    def test_a_reply_that_cannot_be_cleaned_or_is_only_thinking_fails_for_the_other_model(self) -> None:
        for raw in ("<think>Be warm. Ask one question.yaar, ye bhaari hai.", "<think>Be warm.</think>"):
            with self.assertRaises(AgentProviderError):
                _compact_chat_reply(raw, ASKED)


class ClaudeThinkingInTextTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "AGENT_PROMPT_DEBUG": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_a_text_block_that_is_only_thinking_is_dropped_and_the_reply_block_kept(self) -> None:
        client = claude_answer("<think>The user asks for advice. Be warm. Ask at most one question.", "yaar, 5-6 saal ka rishta, ye bahut bhaari hai.")
        with patch("anthropic.AsyncAnthropic", return_value=client), patch("agent.providers.gateway.claude_chat._record") as recorded:
            reply = await claude_chat("You are Omi.", ASKED, model="claude-sonnet-5-5")
        self.assertEqual(reply, "yaar, 5-6 saal ka rishta, ye bahut bhaari hai.")
        # The kinds of block are kept with the usage row, so a reply in pieces can be seen later.
        self.assertEqual(recorded.call_args.kwargs["raw_usage"]["blocks"], ["text", "text"])

    async def test_one_block_with_thinking_and_reply_run_together_fails_for_the_fallback(self) -> None:
        client = claude_answer("<think>Be warm. Ask at most one question.yaar, ye bahut bhaari hai.")
        with patch("anthropic.AsyncAnthropic", return_value=client), patch("agent.providers.gateway.claude_chat._record"), self.assertRaises(AgentProviderError):
            await claude_chat("You are Omi.", ASKED, model="claude-sonnet-5-5")


if __name__ == "__main__":
    unittest.main()
