"""Validates the per-user card that background cognition rewrites."""

from __future__ import annotations

import re
from typing import Any

MAX_USER_CARD_CHARS = 900
_WORD = re.compile(r"[a-z0-9]+")


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


def without_replaced_lines(card: str, replaced: list[tuple[dict[str, Any], str | None]]) -> str:
    """Drop card lines that still say what a memory replaced or retracted in this batch said.

    `replaced` pairs each old memory with the text of what replaced it (None when retracted). A
    line goes when at least half its words, and two or more, are in the old memory and it is
    closer to the old memory than to its replacement, so "Currently studying X" goes after
    "Finished studying X" while a line already saying "Finished studying X" stays.
    """
    kept = []
    for line in card.splitlines():
        words = _words(line)
        if not any(_is_stale(words, _words(_memory_text(old)), _words(new or "")) for old, new in replaced):
            kept.append(line)
    return "\n".join(kept)


def _is_stale(line: set[str], old: set[str], new: set[str]) -> bool:
    shared = line & old
    if len(shared) < 2 or len(shared) / len(line) < 0.5:
        return False
    return _similarity(line, old) > _similarity(line, new)


def _similarity(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left | right else 0.0


def _memory_text(memory: dict[str, Any]) -> str:
    return f"{memory.get('statement') or ''} {memory.get('value') or ''}"


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if len(word) > 2}


__all__ = ["MAX_USER_CARD_CHARS", "validate_user_card", "without_replaced_lines"]
