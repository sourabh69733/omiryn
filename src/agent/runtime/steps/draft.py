"""The first draft: the reply model with tools, a search when it says it does not know, and fallbacks
for a cut-off or malformed answer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.context_engine.conversation_engine.policy.unknown import says_unknown
from agent.outputs.companion_response import structured_companion_reply
from agent.providers import AgentProviderTruncationError
from agent.tools import ToolContext, chat_search_enabled, reply_with_tools, tool_arguments

from .job import ReplyJob
from .unsure_search import search_when_unsure
from .visible import looks_like_model_transport, visible_reply

FALLBACK_MAX_TOKENS = 400


@dataclass(frozen=True)
class Draft:
    reply: str
    fallback_reason: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    chat_search: dict[str, Any] | None = None


async def write_draft(job: ReplyJob) -> Draft:
    fallback_reason = None
    chat_search: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = []
    try:
        context = ToolContext(user_id=job.user_id, conversation_id=job.conversation_id)
        raw = await job.generate(job.reply_messages, **job.generation_arguments, **tool_arguments(context))
        raw, tool_calls = await reply_with_tools(
            raw,
            context=context,
            generate=job.generate,
            reply_messages=job.reply_messages,
            generation_arguments=job.generation_arguments,
        )
        searched = any(call.get("tool") == "search_chats" for call in tool_calls)
        if not searched and job.user_id and chat_search_enabled() and says_unknown(raw):
            raw, chat_search = await search_when_unsure(raw, job)
    except AgentProviderTruncationError:
        fallback_reason = "output_truncated"
        raw = await job.generate(job.reply_messages, **job.generation_arguments, max_tokens=FALLBACK_MAX_TOKENS)

    decoded = structured_companion_reply(raw)
    if fallback_reason is None and decoded is None and looks_like_model_transport(raw):
        fallback_reason = "malformed_structured_output"
        raw = await job.generate(job.reply_messages, **job.generation_arguments, max_tokens=FALLBACK_MAX_TOKENS)
        decoded = structured_companion_reply(raw)
    return Draft(visible_reply(raw, decoded), fallback_reason, tool_calls, chat_search)


__all__ = ["Draft", "write_draft"]
