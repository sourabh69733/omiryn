from __future__ import annotations

import re
from typing import Any

from .config import CHAT_ADVICE_REPLY_WORD_LIMIT, CHAT_REPLY_WORD_LIMIT, RECENT_CHAT_MESSAGE_LIMIT
from .prompts import _context_sources_text, _truncate_for_context
from .quality import _normalized_user_text


def _user_message_count(messages: list[dict[str, str]]) -> int:
    return sum(1 for message in messages if message.get("role") == "user")

def _messages_for_profile_extraction(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        message
        for message in messages
        if message.get("quality") != "low_information"
    ]

def _user_messages_for_memory_extraction(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            **message,
            "message_index": index,
        }
        for index, message in enumerate(messages)
        if message.get("role") == "user"
        and message.get("quality") != "low_information"
        and message.get("content")
    ]

def _provider_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    provider_messages = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"assistant", "user", "system"} or content is None:
            continue
        provider_messages.append({"role": role, "content": str(content)})
    if len(provider_messages) <= RECENT_CHAT_MESSAGE_LIMIT:
        return provider_messages

    older_messages = provider_messages[:-RECENT_CHAT_MESSAGE_LIMIT]
    recent_messages = provider_messages[-RECENT_CHAT_MESSAGE_LIMIT:]
    return [_conversation_summary_message(older_messages)] + recent_messages

def _conversation_summary_message(messages: list[dict[str, str]]) -> dict[str, str]:
    user_lines = [
        _truncate_for_context(message["content"], 160)
        for message in messages
        if message["role"] == "user"
    ][-8:]
    assistant_lines = [
        _truncate_for_context(message["content"], 120)
        for message in messages
        if message["role"] == "assistant"
    ][-4:]
    parts = [
        "Earlier conversation summary, compacted locally to save tokens.",
        "Use this only as rough continuity; prefer the recent messages for exact wording.",
    ]
    if user_lines:
        parts.append("Earlier user messages: " + " | ".join(user_lines))
    if assistant_lines:
        parts.append("Earlier assistant prompts: " + " | ".join(assistant_lines))
    return {"role": "system", "content": "\n".join(parts)}

def _conversation_and_context_text(
    messages: list[dict[str, str]],
    context_sources: list[dict[str, Any]] | None,
) -> str:
    conversation_text = "\n".join(
        f"{message['role']}: {message['content']}" for message in messages
    )
    context_text = _context_sources_text(context_sources)
    if not context_text:
        return conversation_text
    return f"{context_text}\n\nConversation:\n{conversation_text}"

def _compact_chat_reply(content: str, messages: list[dict[str, str]]) -> str:
    cleaned = " ".join(content.strip().split())
    if not cleaned:
        return cleaned

    limit = _chat_reply_word_limit(messages)
    words = cleaned.split()
    if len(words) <= limit:
        return cleaned

    sentence_parts = re.split(r"(?<=[.!?।])\s+", cleaned)
    kept: list[str] = []
    count = 0
    for sentence in sentence_parts:
        sentence_words = sentence.split()
        if not sentence_words:
            continue
        if kept and count + len(sentence_words) > limit:
            break
        kept.append(sentence)
        count += len(sentence_words)
        if count >= limit:
            break

    compact = " ".join(kept).strip()
    if compact:
        return compact
    return " ".join(words[:limit]).rstrip(" ,;:")

def _chat_reply_word_limit(messages: list[dict[str, str]]) -> int:
    latest_user_text = _latest_user_text(messages)
    advice_markers = {
        "advice",
        "detail",
        "explain",
        "help",
        "how",
        "plan",
        "suggest",
        "why",
    }
    if any(marker in latest_user_text for marker in advice_markers):
        return CHAT_ADVICE_REPLY_WORD_LIMIT
    return CHAT_REPLY_WORD_LIMIT

def _latest_user_text(messages: list[dict[str, str]]) -> str:
    latest = next(
        (
            message.get("content", "")
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    )
    return _normalized_user_text(str(latest))

def _is_greeting_only(text: str) -> bool:
    normalized = text.strip().lower().strip(".!?, ")
    return normalized in {"hi", "hello", "hey", "hii", "heyy", "namaste"}
