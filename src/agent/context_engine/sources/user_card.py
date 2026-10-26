"""The short card on who the user is, kept across all chats, plus how they describe themselves."""

from __future__ import annotations

from typing import Any

from agent.config import agent_pipeline_config
from storage import get_user_card

USER_CARD_SOURCE_TYPE = "user_card"


def user_card_sources(user_id: str | None) -> list[dict[str, Any]]:
    """The short note on who the user is, kept across all chats by background cognition."""
    if not user_id or agent_pipeline_config().memory_contract_version != 3:
        return []
    card = get_user_card(user_id) or ""
    own_words = self_description(user_id)
    if not card and not own_words:
        return []
    content = (
        "What you know about the user from all your chats. Use it naturally; do not "
        "recite it or say you keep notes.\n" + card
    ).rstrip()
    if own_words:
        # Written by the user on their profile: their own view of themselves, which wins over guesses.
        content += "\nHow they describe themselves on their profile: " + own_words
    return [
        {
            "source_type": USER_CARD_SOURCE_TYPE,
            "title": "About the user",
            "content": content,
            "metadata": {"card_chars": len(card), "self_description": bool(own_words)},
        }
    ]


def self_description(user_id: str) -> str:
    """The intro and tags the user edited on their profile, or "" when Omi wrote them."""
    from storage.vibe_cards import get_vibe_card

    intro = get_vibe_card(user_id).get("intro") or {}
    if not intro.get("edited") or not intro.get("text"):
        return ""
    chips = ", ".join(str(chip) for chip in intro.get("chips") or [])
    return str(intro["text"]) + (f" (tags: {chips})" if chips else "")


__all__ = ["USER_CARD_SOURCE_TYPE", "self_description", "user_card_sources"]
