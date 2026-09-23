"""Normalizes and splits a model response into safe user-facing chat bubbles."""

from __future__ import annotations

import os
import re

from agent.context_engine.conversation_engine.policy.script import normalize_assistant_script

REPLY_PART_SEPARATOR = "<next_message>"
# Normal replies use 1-3 bubbles by prompt; 7 leaves room for a story or scene told in one go.
MAX_REPLY_PARTS = int(os.getenv("AGENT_MAX_REPLY_PARTS", "7"))
REPLY_PART_WORD_LIMIT = int(os.getenv("AGENT_REPLY_PART_WORD_LIMIT", "35"))


def split_assistant_reply(reply: str, *, user_text: str | None = None) -> list[str]:
    cleaned = _soften_adult_safety_refusal(
        " ".join(normalize_assistant_script(str(reply or "")).strip().split()),
        user_text,
    )
    if not cleaned:
        return [""]

    if REPLY_PART_SEPARATOR not in cleaned:
        return [_normalize_chat_bubble(cleaned)]

    raw_parts = [part.strip() for part in cleaned.split(REPLY_PART_SEPARATOR)]

    parts: list[str] = []
    for raw_part in raw_parts:
        parts.extend(_word_limited_parts(_normalize_chat_bubble(raw_part), REPLY_PART_WORD_LIMIT))

    cleaned_parts = [_normalize_chat_bubble(part) for part in parts if part]
    return _limit_parts(cleaned_parts, MAX_REPLY_PARTS) or [_normalize_chat_bubble(cleaned)]


def _word_limited_parts(text: str, word_limit: int) -> list[str]:
    """Split an overlong bubble at sentence ends; only a single huge sentence is cut by words."""
    words = text.split()
    if not words or word_limit <= 0:
        return [text.strip()] if text.strip() else []
    if len(words) <= word_limit:
        return [text.strip()]
    parts: list[str] = []
    current: list[str] = []
    for sentence in re.split(r"(?<=[.!?।])\s+", text.strip()):
        sentence_words = sentence.split()
        if current and len(current) + len(sentence_words) > word_limit:
            parts.append(" ".join(current))
            current = []
        if len(sentence_words) > word_limit:
            parts.extend(
                " ".join(sentence_words[index : index + word_limit])
                for index in range(0, len(sentence_words), word_limit)
            )
            continue
        current.extend(sentence_words)
    if current:
        parts.append(" ".join(current))
    return [part for part in parts if part]


def _limit_parts(parts: list[str], max_parts: int) -> list[str]:
    if max_parts <= 0 or len(parts) <= max_parts:
        return parts
    return parts[:max_parts]


def _strip_wrapping_quotes(text: str) -> str:
    cleaned = text.strip()
    quote_pairs = {
        '"': '"',
        "'": "'",
        "\u201c": "\u201d",
        "\u2018": "\u2019",
    }
    changed = True
    while changed and len(cleaned) >= 2:
        changed = False
        start = cleaned[0]
        end = quote_pairs.get(start)
        if end and cleaned.endswith(end):
            cleaned = cleaned[1:-1].strip()
            changed = True
    return cleaned


def _normalize_chat_bubble(text: str) -> str:
    cleaned = _strip_speaker_label(text)
    return _strip_wrapping_quotes(cleaned)


def _strip_speaker_label(text: str) -> str:
    cleaned = text.strip()
    return re.sub(
        r"^[A-Z][A-Za-z0-9 _.-]{0,30}:\s*",
        "",
        cleaned,
        count=1,
    ).strip()


def _soften_adult_safety_refusal(reply: str, user_text: str | None) -> str:
    if not _looks_like_stock_refusal(reply):
        return reply
    if not _looks_like_adult_flirty_request(user_text or ""):
        return reply
    return (
        "Thoda spicy rakh sakti hoon, bas explicit nahi. "
        "Teasing wali vibe chalegi, full hot scene nahi."
    )


def _looks_like_stock_refusal(reply: str) -> bool:
    normalized = reply.strip().lower()
    refusal_markers = (
        "i'm sorry, but i can't help with that",
        "i am sorry, but i can't help with that",
        "i can't help with that",
        "i cannot help with that",
        "can't assist with that",
        "cannot assist with that",
    )
    return any(marker in normalized for marker in refusal_markers)


def _looks_like_adult_flirty_request(text: str) -> bool:
    normalized = text.lower()
    adult_terms = (
        "adult",
        "double meaning",
        "hot",
        "naughty",
        "sexy",
        "spicy",
        "turn on",
    )
    return any(term in normalized for term in adult_terms)
