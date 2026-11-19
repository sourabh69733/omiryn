"""A chat reply written by Claude, through Anthropic's own SDK.

The reply path speaks the chat format the other providers use: a system prompt, a history of
user, assistant, system and tool messages, and tools offered with "auto". This turns that into a
Claude request and turns the answer back into what the reply steps expect: the reply text, or the
tool-call marker with the calls the model made. Picked by naming a Claude model as the reply model;
any failure raises AgentProviderError, so the reply falls back to the usual model.
"""

from __future__ import annotations

import json
import logging
import os
from time import perf_counter
from typing import Any

from agent.observability.usage import CHAT_REPLY
from agent.providers.shared.errors import AgentProviderError, AgentProviderTruncationError
from agent.providers.shared.messages import _compact_chat_reply, _provider_messages
from agent.providers.shared.usage_events import _emit_prompt_debug, _prompt_debug

from .claude import PROVIDER, _record, claude_key, cost_usd
from .clients import TOOL_CALL_MARKER

logger = logging.getLogger(__name__)

# How hard the model works on a reply (CLAUDE_REPLY_EFFORT). Low is the level meant for chat.
DEFAULT_REPLY_EFFORT = "low"
_EFFORTS = ("low", "medium", "high", "xhigh", "max")
# The model may think before it writes, and thinking counts toward the output limit. The caller's
# limit is for the words a person reads, so this much is added on top for the thinking.
THINKING_ROOM_TOKENS = 4000
# Models that take a system note inside the history. On any other, a note goes as marked user text.
_SYSTEM_NOTES_IN_HISTORY = frozenset({"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"})
_EARLIER_NOT_SHOWN = "(earlier messages are not shown)"


def reply_effort() -> str:
    effort = os.getenv("CLAUDE_REPLY_EFFORT", DEFAULT_REPLY_EFFORT).strip().lower()
    return effort if effort in _EFFORTS else DEFAULT_REPLY_EFFORT


async def claude_chat(
    system_prompt: str,
    messages: list[dict[str, Any]],
    *,
    model: str,
    conversation_id: str | None = None,
    request_kind: str = CHAT_REPLY,
    timeout_seconds: float | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | str | None = None,
    max_tokens: int | None = None,
) -> str:
    """The reply text, or the tool-call marker and calls when the model asked for tools."""
    import anthropic

    key = claude_key()
    if not key:
        raise AgentProviderError("ANTHROPIC_API_KEY is required for a Claude reply model.")
    provider_messages = _provider_messages(messages)
    lead_notes, history = claude_messages(provider_messages, model)
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": (max_tokens or 1200) + THINKING_ROOM_TOKENS,
        "system": "\n\n".join([system_prompt, *lead_notes]),
        "messages": history,
        # No temperature (the current models reject sampling settings) and thinking is left to the
        # model; effort sets how much.
        "output_config": {"effort": reply_effort()},
    }
    if tools:
        request["tools"] = [claude_tool(tool) for tool in tools]
        choice = claude_tool_choice(tool_choice)
        if choice:
            request["tool_choice"] = choice
    prompt_debug = _prompt_debug(system_prompt, provider_messages)
    _emit_prompt_debug(PROVIDER, model, request_kind, prompt_debug)
    # One quick second try on a dropped connection; a slow model is the caller's fallback to handle.
    client = anthropic.AsyncAnthropic(api_key=key, timeout=timeout_seconds or 60.0, max_retries=1)
    started = perf_counter()
    try:
        response = await client.messages.create(**request)
    except anthropic.APIStatusError as error:
        _record(request_kind, conversation_id, model, started, success=False, raw_usage={"error_status_code": error.status_code, "prompt_debug": prompt_debug})
        raise AgentProviderError(f"Claude returned HTTP {error.status_code}") from error
    except anthropic.APIConnectionError as error:  # a timeout is one of these
        _record(request_kind, conversation_id, model, started, success=False, raw_usage={"prompt_debug": prompt_debug})
        raise AgentProviderError(f"Could not reach Claude ({type(error).__name__})") from error
    finally:
        await client.close()
    usage = {
        "model": response.model,
        "input_tokens": int(response.usage.input_tokens or 0),
        "output_tokens": int(response.usage.output_tokens or 0),
    }
    usage["cost_usd"] = cost_usd(model, usage["input_tokens"], usage["output_tokens"])
    stopped = str(response.stop_reason or "")
    raw_usage = {"finish_reason": stopped, "prompt_debug": prompt_debug}
    _record(request_kind, conversation_id, model, started, success=stopped not in {"refusal", "max_tokens"}, usage=usage, raw_usage=raw_usage)
    if stopped == "refusal":
        raise AgentProviderError("Claude declined this request")
    if stopped == "max_tokens":
        raise AgentProviderTruncationError("anthropic stopped at the output-token limit (max_tokens).")
    calls = [
        {"name": block.name, "arguments": block.input if isinstance(block.input, dict) else {}}
        for block in response.content
        if block.type == "tool_use"
    ]
    if calls and isinstance(tool_choice, dict):
        return json.dumps(calls[0]["arguments"])  # a named tool: its arguments are the answer
    if calls:
        return TOOL_CALL_MARKER + json.dumps({"calls": calls})
    content = "".join(block.text for block in response.content if block.type == "text")
    return _compact_chat_reply(content, messages) if request_kind == CHAT_REPLY else content


def claude_messages(provider_messages: list[dict[str, Any]], model: str) -> tuple[list[str], list[dict[str, Any]]]:
    """(notes for the system prompt, the history in Claude's shape).

    System messages before the first turn join the system prompt. A later one stays a system note
    where Claude takes it: after a user turn, and last or followed by an assistant turn. Anywhere
    else it goes as user text marked as the app's note. Tool calls become tool_use blocks and their
    results tool_result blocks in the user turn that follows.
    """
    lead_notes: list[str] = []
    history: list[dict[str, Any]] = []
    for message in provider_messages:
        role, text = message.get("role"), str(message.get("content") or "")
        if role == "system":
            if not text:
                continue
            if not history:
                lead_notes.append(text)
            elif history[-1]["role"] == "system":
                history[-1]["content"] += "\n\n" + text
            else:
                history.append({"role": "system", "content": text})
        elif role == "tool":
            result = {"type": "tool_result", "tool_use_id": str(message.get("tool_call_id") or ""), "content": text}
            if history and _is_tool_results(history[-1]):
                history[-1]["content"].append(result)
            else:
                history.append({"role": "user", "content": [result]})
        elif role == "assistant":
            blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
            blocks.extend(_tool_use(call) for call in message.get("tool_calls") or [] if isinstance(call, dict))
            if blocks:
                history.append({"role": "assistant", "content": blocks})
        elif role == "user" and text:
            history.append({"role": "user", "content": text})
    history = [_placed(message, index, history, model) for index, message in enumerate(history)]
    if history and history[0]["role"] != "user":
        history.insert(0, {"role": "user", "content": _EARLIER_NOT_SHOWN})
    if not history or history[-1]["role"] == "assistant":
        # Claude continues from a user turn; a message Omi starts on its own has none to answer.
        history.append({"role": "user", "content": _app_note("Write your next message now.")})
    return lead_notes, history


def _placed(message: dict[str, Any], index: int, history: list[dict[str, Any]], model: str) -> dict[str, Any]:
    if message["role"] != "system":
        return message
    after_user = index > 0 and history[index - 1]["role"] == "user"
    before_assistant_or_last = index == len(history) - 1 or history[index + 1]["role"] == "assistant"
    if model in _SYSTEM_NOTES_IN_HISTORY and after_user and before_assistant_or_last:
        return message
    return {"role": "user", "content": _app_note(message["content"])}


def _app_note(text: str) -> str:
    return f"[Note from the app, not from the person: {text}]"


def _is_tool_results(message: dict[str, Any]) -> bool:
    content = message.get("content")
    return message.get("role") == "user" and isinstance(content, list) and all(block.get("type") == "tool_result" for block in content)


def _tool_use(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function") if isinstance(call.get("function"), dict) else call
    raw = function.get("arguments")
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        arguments = {"arguments": raw}  # the history keeps long arguments cut short
    return {
        "type": "tool_use",
        "id": str(call.get("id") or ""),
        "name": str(function.get("name") or ""),
        "input": arguments if isinstance(arguments, dict) else {},
    }


def claude_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """A tool in the chat API's shape ({"type": "function", "function": {...}}) as Claude's."""
    function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
    return {
        "name": str(function.get("name") or ""),
        "description": str(function.get("description") or ""),
        "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
    }


def claude_tool_choice(tool_choice: dict[str, Any] | str | None) -> dict[str, Any] | None:
    if isinstance(tool_choice, dict):
        function = tool_choice.get("function")
        name = str(function.get("name") or "") if isinstance(function, dict) else ""
        return {"type": "tool", "name": name} if name else None
    return {"auto": {"type": "auto"}, "none": {"type": "none"}, "required": {"type": "any"}}.get(str(tool_choice or ""))


__all__ = ["DEFAULT_REPLY_EFFORT", "claude_chat", "claude_messages", "claude_tool", "claude_tool_choice", "reply_effort"]
