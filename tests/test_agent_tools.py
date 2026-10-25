"""Tools for the reply model: a registry, parallel calls with limits, and a loop that always replies."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from agent.providers.gateway.clients import TOOL_CALL_MARKER, _called_tool, parse_tool_calls
from agent.tools import Tool, ToolCall, ToolContext, ToolResult, reply_with_tools, run_calls, tool_arguments, tool_specs
from agent.tools import registry

CONTEXT = ToolContext("tools-user", "omi")


def _calls(*calls: tuple[str, dict]) -> str:
    return TOOL_CALL_MARKER + json.dumps({"calls": [{"name": name, "arguments": arguments} for name, arguments in calls]})


async def _echo(arguments: dict, context: ToolContext) -> ToolResult:
    return ToolResult(f"echo {arguments.get('text')}", {"chars": len(str(arguments.get("text")))})


async def _slow(arguments: dict, context: ToolContext) -> ToolResult:
    await asyncio.sleep(1)
    return ToolResult("late")


async def _broken(arguments: dict, context: ToolContext) -> ToolResult:
    raise RuntimeError("down")


class ToolsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.saved = dict(registry._TOOLS)
        registry.register_tool(Tool("echo", "Echo text.", {"type": "object", "properties": {"text": {"type": "string"}}}, _echo))
        registry.register_tool(Tool("slow", "Slow.", {"type": "object"}, _slow, timeout_seconds=0.05))
        registry.register_tool(Tool("broken", "Broken.", {"type": "object"}, _broken))
        registry.register_tool(Tool("off", "Off.", {"type": "object"}, _echo, enabled=lambda context: False))

    def tearDown(self) -> None:
        registry._TOOLS.clear()
        registry._TOOLS.update(self.saved)

    def test_specs_list_only_tools_that_are_on(self) -> None:
        names = [spec["function"]["name"] for spec in tool_specs(CONTEXT)]
        self.assertIn("search_chats", names)
        self.assertIn("echo", names)
        self.assertNotIn("off", names)
        self.assertNotIn("search_chats", [spec["function"]["name"] for spec in tool_specs(ToolContext(None))])

    def test_tools_can_be_switched_off(self) -> None:
        self.assertEqual(tool_arguments(CONTEXT)["tool_choice"], "auto")
        with patch.dict("os.environ", {"AGENT_TOOLS": "false"}):
            self.assertEqual(tool_arguments(CONTEXT), {})

    def test_the_gateway_keeps_every_call(self) -> None:
        message = {"tool_calls": [
            {"function": {"name": "echo", "arguments": '{"text": "a"}'}},
            {"function": {"name": "echo", "arguments": "not json"}},
        ]}
        self.assertEqual(parse_tool_calls(_called_tool(message)), [("echo", {"text": "a"}), ("echo", {})])
        self.assertEqual(parse_tool_calls(TOOL_CALL_MARKER + '{"name": "echo", "arguments": {"text": "old"}}'), [("echo", {"text": "old"})])
        self.assertEqual(parse_tool_calls("a plain reply"), [])

    async def test_calls_run_together_and_failures_become_notes(self) -> None:
        results = await run_calls([ToolCall("echo", {"text": "hi"}), ToolCall("slow", {}), ToolCall("broken", {}), ToolCall("nope", {}), ToolCall("off", {})], CONTEXT)
        self.assertEqual(results[0].note, "echo hi")
        self.assertEqual((results[0].trace["ok"], results[0].trace["chars"]), (True, 2))
        self.assertEqual(results[1].trace["error"], "timeout")
        self.assertEqual(results[2].trace["error"], "RuntimeError")
        self.assertEqual(results[3].trace["error"], "unknown_tool")
        self.assertEqual(results[4].trace["error"], "unknown_tool")
        self.assertIn("Do not guess", results[1].note)

    async def test_the_model_can_call_again_after_reading_results(self) -> None:
        writer = AsyncMock(side_effect=[_calls(("echo", {"text": "second"})), "Done."])
        reply, trace = await reply_with_tools(
            _calls(("echo", {"text": "one"}), ("echo", {"text": "two"})),
            context=CONTEXT, generate=writer, reply_messages=[{"role": "user", "content": "hi"}], generation_arguments={"model": "m"},
        )
        self.assertEqual(reply, "Done.")
        self.assertEqual([(entry["round"], entry["chars"]) for entry in trace], [(1, 3), (1, 3), (2, 6)])
        first, second = writer.await_args_list
        self.assertIn("echo one", first.args[0][-1]["content"])
        self.assertIn("echo two", first.args[0][-1]["content"])
        self.assertIn("tools", first.kwargs)
        self.assertIn("echo second", second.args[0][-1]["content"])

    async def test_the_last_round_offers_no_tools_and_always_replies(self) -> None:
        call = _calls(("echo", {"text": "x"}))
        writer = AsyncMock(side_effect=[call, call, "Finally."])
        reply, trace = await reply_with_tools(call, context=CONTEXT, generate=writer, reply_messages=[], generation_arguments={}, max_rounds=2)
        self.assertEqual(reply, "Finally.")
        self.assertEqual(len(trace), 2)
        self.assertNotIn("tools", writer.await_args_list[1].kwargs)

    async def test_calls_per_round_are_capped(self) -> None:
        many = _calls(*[("echo", {"text": str(i)}) for i in range(9)])
        _, trace = await reply_with_tools(many, context=CONTEXT, generate=AsyncMock(return_value="ok"), reply_messages=[], generation_arguments={})
        self.assertEqual(len(trace), 4)


if __name__ == "__main__":
    unittest.main()
