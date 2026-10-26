"""Keeps a story going across turns once the companion has started telling one."""

from __future__ import annotations

from typing import Any


def continues_story(user_text: str, history: list[dict[str, Any]]) -> bool:
    """True while a story the companion is telling has not ended.

    Whether the user's message follows the story or moves on is left to the model: the story
    turn note tells it to reply to a change of subject and mark the story ended. Keyword lists
    for "then?" or "stop" missed too much wording, Hinglish included.
    """
    last_reply = next((m for m in reversed(history) if m.get("role") == "assistant"), None)
    return bool(last_reply and last_reply.get("story") and not last_reply.get("story_end"))


__all__ = ["continues_story"]
