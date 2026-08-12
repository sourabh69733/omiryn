"""Owns the stable boundary between raw model output and companion-facing replies."""

from .decoder import (
    structured_companion_payload,
    structured_companion_reply,
    textual_tool_arguments,
)

__all__ = [
    "structured_companion_payload",
    "structured_companion_reply",
    "textual_tool_arguments",
]
