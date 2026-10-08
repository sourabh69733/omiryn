"""Prepares bounded messages and extraction conversation text."""

from __future__ import annotations

import re
from typing import Any

from agent.context_engine.conversation_engine.policy.replies import (
    MAX_REPLY_PARTS,
    REPLY_PART_SEPARATOR,
    REPLY_PART_WORD_LIMIT,
    STORY_NOTE_PREFIX,
    has_story_marker,
    normalize_part_separators,
)

from .config import (
    CHAT_ADVICE_REPLY_WORD_LIMIT,
    CHAT_REPLY_WORD_LIMIT,
    HISTORY_TOKEN_BUDGET,
    PREVIOUS_SESSION_TAIL,
    RECENT_CHAT_MESSAGE_LIMIT,
)
from agent.providers.companion.prompts import _context_sources_text, _truncate_for_context
from agent.providers.companion.quality import _normalized_user_text
from agent.shared.timeline import current_session_start, day_notes
from agent.shared.tokens import estimate_tokens


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

def reply_window(
    messages: list[dict[str, Any]],
    summarized_through: int | None,
    timezone_name: str | None = None,
) -> list[dict[str, Any]]:
    """Messages to send as chat history, each with a `day_note` in the user's timezone.

    Drops messages the conversation summary already covers: everything before the recent
    window, and earlier sessions except the last few messages before the latest break.
    Messages the summary has not reached yet always stay; `_provider_messages` then compacts
    only that unsummarized overflow.
    """
    start = 0
    if summarized_through is not None and summarized_through >= 0:
        start = min(max(0, len(messages) - RECENT_CHAT_MESSAGE_LIMIT), summarized_through + 1)
        # Older sessions reach the model through the dated summary, so it does not copy stale
        # relative words. The tail of the previous session stays: it is what "last time" means.
        session_start = current_session_start(messages)
        previous_start = current_session_start(messages[:session_start])
        keep_from = max(previous_start, session_start - PREVIOUS_SESSION_TAIL)
        start = max(start, min(keep_from, summarized_through + 1))
    window = messages[start:]
    return [
        {**message, "day_note": note}
        for message, note in zip(window, day_notes(window, timezone_name), strict=True)
    ]


def summarized_through(context_sources: list[dict[str, Any]] | None) -> int | None:
    """Last message index covered by the conversation summary included in context, if any."""
    for source in context_sources or []:
        if source.get("source_type") == "conversation_summary":
            value = (source.get("metadata") or {}).get("processed_through_message_index")
            return value if isinstance(value, int) else None
    return None


def _reply_quote_note(message: dict[str, Any]) -> str:
    """Which earlier message the user is replying to, so the model knows what "this" means."""
    reply_to = message.get("reply_to")
    if message.get("role") != "user" or not isinstance(reply_to, dict):
        return ""
    if reply_to.get("deleted") or not reply_to.get("text"):
        return "[Replying to a message they later deleted]"
    whose = "your message" if reply_to.get("role") == "assistant" else "their own earlier message"
    return f'[Replying to {whose}: "{reply_to["text"]}"]'


def _provider_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    provider_messages = []
    # reply_window() already computed notes in the user's timezone; otherwise use the default.
    notes = (
        [message.get("day_note") for message in messages]
        if any("day_note" in message for message in messages)
        else day_notes(messages)
    )
    for message, note in zip(messages, notes, strict=True):
        role = message.get("role")
        content = message.get("content")
        if role not in {"assistant", "user", "system"} or content is None or message.get("deleted"):
            continue
        text = str(content)
        quote = _reply_quote_note(message)
        if quote:
            text = f"{quote} {text}"
        if note:
            text = f"{note} {text}"
        provider_messages.append({"role": role, "content": text})
    provider_messages = _merge_adjacent_assistant_messages(provider_messages)
    if len(provider_messages) <= RECENT_CHAT_MESSAGE_LIMIT:
        return _fit_history(provider_messages, HISTORY_TOKEN_BUDGET)

    older_messages = provider_messages[:-RECENT_CHAT_MESSAGE_LIMIT]
    recent_messages = provider_messages[-RECENT_CHAT_MESSAGE_LIMIT:]
    return _fit_history(
        [_conversation_summary_message(older_messages)] + recent_messages,
        HISTORY_TOKEN_BUDGET,
    )


# The newest messages are never shortened or dropped; they carry the current exchange.
_PROTECTED_RECENT_MESSAGES = 4
_LONG_MESSAGE_CHARS = 1200


def _fit_history(messages: list[dict[str, str]], budget: int) -> list[dict[str, str]]:
    """Keep chat history within an estimated token budget.

    Long pasted messages outside the newest few are shortened first; if that is not
    enough, the oldest messages are dropped, starting with the local summary line.
    """

    def total(items: list[dict[str, str]]) -> int:
        return sum(estimate_tokens(item["content"]) for item in items)

    if budget <= 0 or total(messages) <= budget:
        return messages
    protected_from = max(0, len(messages) - _PROTECTED_RECENT_MESSAGES)
    fitted = [
        {**message, "content": _truncate_for_context(message["content"], _LONG_MESSAGE_CHARS)}
        if index < protected_from
        else message
        for index, message in enumerate(messages)
    ]
    while len(fitted) > _PROTECTED_RECENT_MESSAGES and total(fitted) > budget:
        fitted.pop(0)
    return fitted

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
    cleaned = " ".join(normalize_part_separators(content).strip().split())
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
    if (
        REPLY_PART_SEPARATOR in reply_text
        or _wants_continuous_reply(latest_user_text)
        or _is_story_turn(messages)
        or has_story_marker(reply_text)
    ):
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

def _is_story_turn(messages: list[dict[str, str]]) -> bool:
    """A story note follows the latest user message (set even for "then?" mid-story)."""
    for message in reversed(messages):
        if message.get("role") == "user":
            return False
        if message.get("role") == "system" and str(message.get("content") or "").startswith(
            STORY_NOTE_PREFIX
        ):
            return True
    return False

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
