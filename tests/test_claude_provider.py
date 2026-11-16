"""The Claude path for the read: what is sent, what comes back, and falling back to the usual model
when Claude cannot write it. No network: the SDK client is replaced."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anthropic

from agent.providers import write_chat_read
from agent.providers.gateway.claude import ClaudeUnavailable, claude_json, claude_key, cost_usd, is_claude

SCHEMA = {"type": "object", "properties": {"headline": {"type": "string"}}, "required": ["headline"], "additionalProperties": False}


def reply(text: str, stop_reason: str = "end_turn", model: str = "claude-sonnet-5-5"):
    return SimpleNamespace(
        model=model, stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10_000, output_tokens=500),
    )


def fake_client(answer=None, error: Exception | None = None):
    plain = AsyncMock(return_value=answer, side_effect=error)
    beta = AsyncMock(return_value=answer, side_effect=error)
    client = SimpleNamespace(messages=SimpleNamespace(create=plain), beta=SimpleNamespace(messages=SimpleNamespace(create=beta)), close=AsyncMock())
    return client, plain, beta


class ClaudeJsonTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_the_request_asks_for_json_and_sonnet_and_opus_get_the_refusal_fallback(self) -> None:
        client, plain, beta = fake_client(reply('{"headline": "Two friends"}'))
        with patch("anthropic.AsyncAnthropic", return_value=client) as made:
            data, usage = await claude_json("system", "the chat", model="claude-sonnet-5-5", schema=SCHEMA, request_kind="chat_read")
        self.assertEqual(data, {"headline": "Two friends"})
        self.assertEqual(made.call_args.kwargs["api_key"], "test-key")
        plain.assert_not_awaited()
        sent = beta.await_args.kwargs
        self.assertEqual((sent["model"], sent["system"], sent["messages"]), ("claude-sonnet-5-5", "system", [{"role": "user", "content": "the chat"}]))
        self.assertEqual(sent["output_config"], {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}})
        self.assertEqual((sent["betas"], sent["fallbacks"]), (["server-side-fallback-2026-07-01"], "default"))
        self.assertNotIn("temperature", sent)
        self.assertNotIn("thinking", sent)
        self.assertEqual((usage["input_tokens"], usage["output_tokens"], usage["cost_usd"]), (10_000, 500, 0.025))
        client.close.assert_awaited()

    async def test_haiku_goes_without_the_fallback(self) -> None:
        client, plain, beta = fake_client(reply("{}", model="claude-haiku-5-5"))
        with patch("anthropic.AsyncAnthropic", return_value=client):
            await claude_json("s", "t", model="claude-haiku-5-5", schema=SCHEMA, request_kind="chat_read")
        beta.assert_not_awaited()
        self.assertNotIn("fallbacks", plain.await_args.kwargs)

    async def test_no_key_a_refusal_a_cut_answer_and_an_api_error_all_mean_unavailable(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "CLAUDE_API_KEY": ""}):
            with self.assertRaises(ClaudeUnavailable):
                await claude_json("s", "t", model="claude-opus-5-5", schema=SCHEMA, request_kind="chat_read")
        for answer in (reply("", stop_reason="refusal"), reply('{"headline": "cut off', stop_reason="max_tokens"), reply("[1, 2]")):
            client, _, _ = fake_client(answer)
            with patch("anthropic.AsyncAnthropic", return_value=client), self.assertRaises(ClaudeUnavailable):
                await claude_json("s", "t", model="claude-opus-5-5", schema=SCHEMA, request_kind="chat_read")
        client, _, _ = fake_client(error=anthropic.APIConnectionError(request=SimpleNamespace()))
        with patch("anthropic.AsyncAnthropic", return_value=client), self.assertRaises(ClaudeUnavailable):
            await claude_json("s", "t", model="claude-opus-5-5", schema=SCHEMA, request_kind="chat_read")
        client.close.assert_awaited()

    def test_small_things(self) -> None:
        self.assertTrue(is_claude("claude-haiku-5-5"))
        self.assertFalse(is_claude("Qwen/Qwen3-235B-A22B-Instruct-2507"))
        self.assertFalse(is_claude(None))
        self.assertEqual(cost_usd("claude-opus-5-5", 1_000_000, 100_000), 6.0)
        self.assertIsNone(cost_usd("some-other-model", 1, 1))
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "CLAUDE_API_KEY": "second-name"}):
            self.assertEqual(claude_key(), "second-name")


class ReadRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_claude_model_writes_the_read_and_the_usual_model_steps_in_when_it_cannot(self) -> None:
        usual = AsyncMock(return_value={"headline": "from the usual model"})
        with patch.dict(os.environ, {"AGENT_PROVIDER": "deepinfra", "CHAT_READ_MODEL": "claude-sonnet-5-5"}), patch("agent.providers.extraction.service._upload_call", usual):
            with patch("agent.providers.gateway.claude.claude_json", AsyncMock(return_value=({"headline": "from Claude"}, {}))) as claude:
                self.assertEqual(await write_chat_read("payload", conversation_id="c"), {"headline": "from Claude"})
                self.assertEqual(claude.await_args.kwargs["model"], "claude-sonnet-5-5")
                usual.assert_not_awaited()
            with patch("agent.providers.gateway.claude.claude_json", AsyncMock(side_effect=ClaudeUnavailable("down"))):
                self.assertEqual(await write_chat_read("payload", conversation_id="c"), {"headline": "from the usual model"})
            # The fallback call does not carry the Claude model id to the other provider.
            self.assertFalse(str(usual.await_args.args[4] or "").startswith("claude-"))

    async def test_without_the_setting_claude_is_never_called(self) -> None:
        usual = AsyncMock(return_value={})
        with patch.dict(os.environ, {"AGENT_PROVIDER": "deepinfra", "CHAT_READ_MODEL": ""}), patch("agent.providers.extraction.service._upload_call", usual), patch("agent.providers.gateway.claude.claude_json", AsyncMock()) as claude:
            await write_chat_read("payload", conversation_id="c")
        claude.assert_not_awaited()
        usual.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
