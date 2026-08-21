"""Coordinates one background analytical call across memory and thread domains."""

from .prompt import BACKGROUND_COGNITION_SYSTEM_PROMPT, background_cognition_prompt

__all__ = [
    "BACKGROUND_COGNITION_SYSTEM_PROMPT",
    "background_cognition_prompt",
]
