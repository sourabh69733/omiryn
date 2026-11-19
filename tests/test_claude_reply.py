"""Claude as the reply model: what is sent, what comes back, who gets it, and the usual model
stepping in when Claude cannot reply. No network: the SDK client is replaced."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anthropic

from agent.providers.companion.service import generate_agent_reply, reply_fallback_model
from agent.providers.gateway.claude_chat import claude_chat, claude_messages, claude_tool, claude_tool_choice
from agent.providers.gateway.clients import parse_tool_calls
from agent.providers.shared.errors import AgentProviderError, AgentProviderTruncationError
from agent.providers.shared.model_catalog import model_choices, preferred_reply_model

HAIKU = "claude-haiku-5-5"
RUNTIME = {"provider": "deepinfra", "model": "google/gemma-4-31B-it", "available_models": ["google/gemma-4-31B-it"]}
SEARCH = {"type": "function", "function": {"name": "search_chats", "description": "Find lines.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}


def answer(*blocks, stop_reason: str = "end_turn"):
    return SimpleNamespace(model=HAIKU, stop_reason=stop_reason, content=list(blocks), usage=SimpleNamespace(input_tokens=6000, output_tokens=200))


def text(value: str):
    return SimpleNamespace(type="text", text=value)


def fake_client(result=None, error: Exception | None = None):
    create = AsyncMock(return_value=result, side_effect=error)
    return SimpleNamespace(messages=SimpleNamespace(create=create), close=AsyncMock()), create


class ClaudeMessagesTest(unittest.TestCase):
    def test_notes_tools_and_results_take_claudes_shape(self) -> None:
        notes, history = claude_messages([
            {"role": "system", "content": "Earlier summary."},
            {"role": "user", "content": "what did Riya say about Goa?"},
            {"role": "system", "content": "One question at most."},
            {"role": "system", "content": "Keep it short."},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1_1", "type": "function", "function": {"name": "search_chats", "arguments": '{"query": "Goa"}'}}]},
            {"role": "tool", "tool_call_id": "call_1_1", "content": "Riya: Goa in March?"},
        ], HAIKU)
        self.assertEqual(notes, ["Earlier summary."])
        self.assertEqual(history, [
            {"role": "user", "content": "what did Riya say about Goa?"},
            # After a user turn and before an assistant turn: a real system note, merged into one.
            {"role": "system", "content": "One question at most.\n\nKeep it short."},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call_1_1", "name": "search_chats", "input": {"query": "Goa"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1_1", "content": "Riya: Goa in March?"}]},
        ])

    def test_a_note_claude_would_reject_there_goes_as_marked_user_text(self) -> None:
        # After an assistant turn (a message Omi starts on its own), and on a model without notes in history.
        _, history = claude_messages([{"role": "assistant", "content": "morning!"}, {"role": "system", "content": "Check in about the interview."}], HAIKU)
        self.assertEqual([message["role"] for message in history], ["user", "assistant", "user"])
        self.assertEqual(history[0]["content"], "(earlier messages are not shown)")
        self.assertEqual(history[2]["content"], "[Note from the app, not from the person: Check in about the interview.]")
        _, history = claude_messages([{"role": "user", "content": "hi"}, {"role": "system", "content": "Be brief."}], "claude-sonnet-5")
        self.assertEqual(history[1], {"role": "user", "content": "[Note from the app, not from the person: Be brief.]"})

    def test_history_never_ends_on_omis_own_turn(self) -> None:
        _, history = claude_messages([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey"}], HAIKU)
        self.assertEqual(history[-1]["role"], "user")

    def test_tools_and_tool_choice(self) -> None:
        self.assertEqual(claude_tool(SEARCH), {"name": "search_chats", "description": "Find lines.", "input_schema": SEARCH["function"]["parameters"]})
        self.assertEqual(claude_tool_choice("auto"), {"type": "auto"})
        self.assertEqual(claude_tool_choice({"type": "function", "function": {"name": "search_chats"}}), {"type": "tool", "name": "search_chats"})
        self.assertIsNone(claude_tool_choice(None))


class ClaudeChatTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "AGENT_PROMPT_DEBUG": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_a_reply_is_asked_for_at_low_effort_and_comes_back_as_text(self) -> None:
        client, create = fake_client(answer(SimpleNamespace(type="thinking", thinking=""), text("that sounds rough. what happened?")))
        with patch("anthropic.AsyncAnthropic", return_value=client) as made:
            reply = await claude_chat("You are Omi.", [{"role": "user", "content": "bad day"}], model=HAIKU, tools=[SEARCH], tool_choice="auto", max_tokens=1200, timeout_seconds=25)
        self.assertEqual(reply, "that sounds rough. what happened?")
        self.assertEqual((made.call_args.kwargs["timeout"], made.call_args.kwargs["max_retries"]), (25, 1))
        sent = create.await_args.kwargs
        self.assertEqual((sent["model"], sent["system"], sent["output_config"]), (HAIKU, "You are Omi.", {"effort": "low"}))
        self.assertEqual(sent["max_tokens"], 5200)  # the caller's limit plus room to think
        self.assertEqual((sent["tools"][0]["name"], sent["tool_choice"]), ("search_chats", {"type": "auto"}))
        self.assertNotIn("temperature", sent)
        self.assertNotIn("thinking", sent)
        client.close.assert_awaited()

    async def test_tool_calls_come_back_the_way_the_tool_loop_reads_them(self) -> None:
        client, _ = fake_client(answer(SimpleNamespace(type="tool_use", id="t1", name="search_chats", input={"query": "Goa"}), stop_reason="tool_use"))
        with patch("anthropic.AsyncAnthropic", return_value=client):
            reply = await claude_chat("s", [{"role": "user", "content": "what did she say?"}], model=HAIKU, tools=[SEARCH], tool_choice="auto")
        self.assertEqual(parse_tool_calls(reply), [("search_chats", {"query": "Goa"})])

    async def test_a_refusal_a_cut_reply_an_error_and_no_key_all_raise_for_the_fallback(self) -> None:
        for result, expected in ((answer(stop_reason="refusal"), AgentProviderError), (answer(text("cut"), stop_reason="max_tokens"), AgentProviderTruncationError)):
            client, _ = fake_client(result)
            with patch("anthropic.AsyncAnthropic", return_value=client), self.assertRaises(expected):
                await claude_chat("s", [{"role": "user", "content": "hi"}], model=HAIKU)
        client, _ = fake_client(error=anthropic.APIConnectionError(request=SimpleNamespace()))
        with patch("anthropic.AsyncAnthropic", return_value=client), self.assertRaises(AgentProviderError):
            await claude_chat("s", [{"role": "user", "content": "hi"}], model=HAIKU)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "CLAUDE_API_KEY": ""}), self.assertRaises(AgentProviderError):
            await claude_chat("s", [{"role": "user", "content": "hi"}], model=HAIKU)


class ReplyRoutingTest(unittest.IsolatedAsyncioTestCase):
    MESSAGES = [{"role": "user", "content": "I finally told my manager I want to switch teams"}]

    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"AGENT_PROVIDER": "deepinfra", "DEEPINFRA_MODEL": "google/gemma-4-31B-it", "ANTHROPIC_API_KEY": "test-key", "AGENT_REPLY_FALLBACK_MODEL": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_a_claude_model_replies_through_claude_and_any_other_through_the_provider(self) -> None:
        with patch("agent.providers.companion.service.claude_chat", AsyncMock(return_value="from Claude")) as claude, patch("agent.providers.companion.service.provider_chat", AsyncMock(return_value="from the provider")) as usual:
            self.assertEqual(await generate_agent_reply(self.MESSAGES, model=HAIKU, system_prompt="s"), "from Claude")
            self.assertEqual(claude.await_args.kwargs["model"], HAIKU)
            usual.assert_not_awaited()
            self.assertEqual(await generate_agent_reply(self.MESSAGES, model=None, system_prompt="s"), "from the provider")

    async def test_the_providers_model_steps_in_when_claude_fails_or_has_no_key(self) -> None:
        self.assertEqual(reply_fallback_model("deepinfra", HAIKU), "google/gemma-4-31B-it")
        with patch("agent.providers.companion.service.claude_chat", AsyncMock(side_effect=AgentProviderError("down"))), patch("agent.providers.companion.service.provider_chat", AsyncMock(return_value="from the provider")) as usual:
            self.assertEqual(await generate_agent_reply(self.MESSAGES, model=HAIKU, system_prompt="s"), "from the provider")
            self.assertEqual(usual.await_args.kwargs["model"], "google/gemma-4-31B-it")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "CLAUDE_API_KEY": ""}), patch("agent.providers.companion.service.claude_chat", AsyncMock()) as claude, patch("agent.providers.companion.service.provider_chat", AsyncMock(return_value="from the provider")) as usual:
            self.assertEqual(await generate_agent_reply(self.MESSAGES, model=HAIKU, system_prompt="s"), "from the provider")
            claude.assert_not_awaited()
            self.assertIsNone(usual.await_args.kwargs["model"])


class ReplyModelSettingsTest(unittest.TestCase):
    def test_claude_is_the_default_or_a_choice_only_when_named_and_keyed(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "AGENT_REPLY_MODEL": HAIKU, "CLAUDE_REPLY_MODELS": "claude-sonnet-5-5, not-claude"}), patch("agent.providers.shared.model_catalog.get_reply_model", return_value=None):
            catalog = model_choices(RUNTIME)
            self.assertEqual(catalog["default"], HAIKU)
            self.assertEqual([choice["id"] for choice in catalog["choices"]], [HAIKU, "google/gemma-4-31B-it", "claude-sonnet-5-5"])
            self.assertEqual(catalog["choices"][0]["name"], "Claude Haiku")
            self.assertEqual(preferred_reply_model("someone"), HAIKU)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "CLAUDE_API_KEY": "", "AGENT_REPLY_MODEL": HAIKU, "CLAUDE_REPLY_MODELS": "claude-sonnet-5-5"}), patch("agent.providers.shared.model_catalog.get_reply_model", return_value=None):
            catalog = model_choices(RUNTIME)
            self.assertEqual((catalog["default"], [choice["id"] for choice in catalog["choices"]]), ("google/gemma-4-31B-it", ["google/gemma-4-31B-it"]))
            self.assertIsNone(preferred_reply_model("someone"))


if __name__ == "__main__":
    unittest.main()
