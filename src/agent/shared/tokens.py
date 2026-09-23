"""Cheap token estimates for budgeting prompts without calling a tokenizer."""

from __future__ import annotations

import math


def estimate_tokens(text: str) -> int:
    """Roughly 4 characters per token for ASCII, 2 for other scripts such as Devanagari.

    Errs high for Hindi and emoji so budgets stay safe across English, Hindi and Hinglish.
    """
    ascii_chars = sum(1 for character in text if character.isascii())
    other_chars = len(text) - ascii_chars
    return math.ceil(ascii_chars / 4 + other_chars / 2)


__all__ = ["estimate_tokens"]
