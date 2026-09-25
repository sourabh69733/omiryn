"""Validates the per-user card that background cognition rewrites."""

from __future__ import annotations

from typing import Any

MAX_USER_CARD_CHARS = 900


def validate_user_card(raw: Any) -> str | None:
    """The new card, or None to keep the stored one. Too long is trimmed at a line end."""
    if not isinstance(raw, str):
        return None
    lines = [" ".join(line.split()) for line in raw.strip().splitlines()]
    card = "\n".join(line for line in lines if line)
    if not card:
        return None
    if len(card) <= MAX_USER_CARD_CHARS:
        return card
    cut = card[:MAX_USER_CARD_CHARS]
    line_end = cut.rfind("\n")
    return cut[:line_end] if line_end > 0 else cut


__all__ = ["MAX_USER_CARD_CHARS", "validate_user_card"]
