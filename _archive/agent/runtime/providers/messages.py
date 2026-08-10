from __future__ import annotations

import re
from typing import Any

from agent.runtime.replies import MAX_REPLY_PARTS, REPLY_PART_SEPARATOR, REPLY_PART_WORD_LIMIT

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
            "message_index": message.get("message_index", index),
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
    provider_messages = _merge_adjacent_assistant_messages(provider_messages)
    if len(provider_messages) <= RECENT_CHAT_MESSAGE_LIMIT:
        return provider_messages

    older_messages = provider_messages[:-RECENT_CHAT_MESSAGE_LIMIT]
    recent_messages = provider_messages[-RECENT_CHAT_MESSAGE_LIMIT:]
    return [_conversation_summary_message(older_messages)] + recent_messages

def _conversation_summary_message(messages: list[dict[str, str]]) -> dict[str, str]:
    user_lines = _summary_lines(messages, role="user", limit=5, char_limit=140)
    assistant_lines = _summary_lines(messages, role="assistant", limit=3, char_limit=120)
    parts = [
        "Earlier conversation summary, compacted locally to save tokens.",
        "Use this only as rough continuity; prefer the recent messages for exact wording.",
    ]
    if user_lines:
        parts.append("Earlier user messages: " + " | ".join(user_lines))
    if assistant_lines:
        parts.append("Earlier assistant prompts: " + " | ".join(assistant_lines))
    return {"role": "system", "content": "\n".join(parts)}


def _merge_adjacent_assistant_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    for message in messages:
        if (
            merged
            and message["role"] == "assistant"
            and merged[-1]["role"] == "assistant"
        ):
            merged[-1]["content"] = _join_message_parts(merged[-1]["content"], message["content"])
            continue
        merged.append(dict(message))
    return merged


def _join_message_parts(first: str, second: str) -> str:
    first = first.strip()
    second = second.strip()
    if not first:
        return second
    if not second:
        return first
    return f"{first}\n{second}"


def _summary_lines(
    messages: list[dict[str, str]],
    *,
    role: str,
    limit: int,
    char_limit: int,
) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if message["role"] != role:
            continue
        content = " ".join(str(message.get("content") or "").split())
        if not _summary_worthy(content, role):
            continue
        normalized = _normalized_user_text(content)
        if normalized in seen:
            continue
        seen.add(normalized)
        lines.append(_truncate_for_context(content, char_limit))
    return lines[-limit:]


def _summary_worthy(content: str, role: str) -> bool:
    normalized = _normalized_user_text(content)
    if not normalized:
        return False
    low_signal = {
        "aww thanks",
        "bas",
        "batao",
        "chill",
        "good",
        "glad",
        "ha",
        "haan",
        "hi",
        "hmm",
        "mast",
        "na",
        "nahi",
        "nhi",
        "nice",
        "ok",
        "okay",
        "ohh",
        "thanks",
        "theek",
        "tum sunoa",
        "yep",
        "yes",
    }
    if normalized in low_signal:
        return False
    if len(normalized) <= 3:
        return False
    word_count = len(normalized.split())
    if role == "assistant" and word_count <= 2:
        return False
    return True


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

    limit = _chat_reply_word_limit(messages, cleaned)
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

def _chat_reply_word_limit(
    messages: list[dict[str, str]],
    reply_text: str = "",
) -> int:
    latest_user_text = _latest_user_text(messages)
    if REPLY_PART_SEPARATOR in reply_text or _wants_continuous_reply(latest_user_text):
        return MAX_REPLY_PARTS * REPLY_PART_WORD_LIMIT
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

def _wants_continuous_reply(latest_user_text: str) -> bool:
    continuous_markers = {
        "story",
        "continue",
        "continued",
        "flow",
        "scene",
        "imagine",
        "example",
        "roleplay",
        "parts",
        "sunao",
        "long form",
        "long story",
        "what happened next",
    }
    return any(marker in latest_user_text for marker in continuous_markers)

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
