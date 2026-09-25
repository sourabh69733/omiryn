"""Keeps a story going across turns once the companion has started telling one."""

from __future__ import annotations

from typing import Any

from agent.context_engine.shared.text import normalized_memory_text

# Short replies ("then?", "wow", "aage kya hua") while a story is running mean "keep going".
_SHORT_REPLY_WORDS = 8
_CONTINUE_PHRASES = (
    "continue",
    "go on",
    "keep going",
    "what happened",
    "what next",
    "then",
    "next",
    "more",
    "after that",
    "aage",
    "phir",
    "fir",
    "uske baad",
    "sunao",
)
_STOP_PHRASES = (
    "stop",
    "enough",
    "bas",
    "the end",
    "never mind",
    "nevermind",
    "change the topic",
    "change topic",
    "something else",
    "good night",
    "bye",
)


def continues_story(user_text: str, history: list[dict[str, Any]]) -> bool:
    """True when the last reply was a story and the user is following it, not moving on."""
    last_reply = next((m for m in reversed(history) if m.get("role") == "assistant"), None)
    if not last_reply or not last_reply.get("story"):
        return False
    normalized = normalized_memory_text(user_text)
    if not normalized:
        return True  # an emoji or a bare reaction
    if any(_has_phrase(normalized, phrase) for phrase in _STOP_PHRASES):
        return False
    if len(normalized.split()) <= _SHORT_REPLY_WORDS:
        return True
    return any(_has_phrase(normalized, phrase) for phrase in _CONTINUE_PHRASES)


def _has_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


__all__ = ["continues_story"]
