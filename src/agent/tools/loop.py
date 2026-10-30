"""The tool loop: the reply model calls tools, reads their results, and may call more before replying.

Each round runs every call the model made, at the same time, then asks again with the results added
to the history as tool messages (the model's call, then one `tool` message per result), never as a
system note: a web page or a line from someone's chat is data the model reads, not an instruction
with the prompt's authority. Tools stay offered until the last round; the last call has none, so a
turn always ends in a reply. Limits keep cost bounded: a few rounds, a few calls per round.
"""

from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable

from agent.providers.gateway.clients import parse_tool_calls

from .registry import ToolCall, ToolContext, run_calls, tool_specs

MAX_ROUNDS = 3
MAX_CALLS_PER_ROUND = 4
ARGUMENT_CHARS = 200

Generate = Callable[..., Awaitable[str]]


def tools_enabled() -> bool:
    return os.getenv("AGENT_TOOLS", "true").strip().lower() != "false"


def tool_arguments(context: ToolContext) -> dict[str, Any]:
    """What the first reply call adds to offer tools; empty when none are on."""
    specs = tool_specs(context) if tools_enabled() else []
    return {"tools": specs, "tool_choice": "auto"} if specs else {}


async def reply_with_tools(
    raw_reply: str,
    *,
    context: ToolContext,
    generate: Generate,
    reply_messages: list[dict[str, Any]],
    generation_arguments: dict[str, Any],
    max_rounds: int = MAX_ROUNDS,
) -> tuple[str, list[dict[str, Any]]]:
    """(final reply, one trace entry per call). A plain reply passes through with no calls."""
    messages = list(reply_messages)
    trace: list[dict[str, Any]] = []
    for round_number in range(1, max_rounds + 1):
        called = parse_tool_calls(raw_reply)
        if not called:
            return raw_reply, trace
        calls = [ToolCall(name, arguments) for name, arguments in called[:MAX_CALLS_PER_ROUND]]
        results = await run_calls(calls, context)
        trace.extend({"round": round_number, **result.trace} for result in results)
        messages.extend(tool_result_messages(calls, results, round_number=round_number))
        offer = tool_arguments(context) if round_number < max_rounds else {}
        raw_reply = await generate(list(messages), **generation_arguments, **offer)
    # The last call had no tools, but a model may still answer with a call: never send that.
    if parse_tool_calls(raw_reply):
        raw_reply = await generate(list(messages), **generation_arguments)
    return raw_reply, trace


def tool_result_messages(calls: list[ToolCall], results: list[Any], *, round_number: int = 1) -> list[dict[str, Any]]:
    """The model's calls as one assistant message, then one `tool` message per result.

    The provider layer sends these in the tool-call format of the chat API, so the model reads
    a result as the output of a tool it called. What a tool found is data: it never carries the
    weight of a system message, however it is worded.
    """
    assistant: dict[str, Any] = {"role": "assistant", "content": "", "tool_calls": []}
    tool_messages: list[dict[str, Any]] = []
    for index, (call, result) in enumerate(zip(calls, results), start=1):
        call_id = f"call_{round_number}_{index}"
        arguments = json.dumps(call.arguments, ensure_ascii=False)[:ARGUMENT_CHARS]
        assistant["tool_calls"].append({"id": call_id, "name": call.name, "arguments": arguments})
        tool_messages.append({"role": "tool", "tool_call_id": call_id, "name": call.name, "content": result.note})
    return [assistant, *tool_messages]


__all__ = ["MAX_CALLS_PER_ROUND", "MAX_ROUNDS", "reply_with_tools", "tool_arguments", "tool_result_messages", "tools_enabled"]
