"""Turning raw model output into the text the user sees, never private JSON or tool syntax."""

from __future__ import annotations

from agent.outputs.companion_response import structured_companion_reply
from agent.providers import AgentProviderError


def looks_like_model_transport(raw_text: str) -> bool:
    """Identify private JSON/tool syntax that must not be rendered as companion text."""
    text = str(raw_text or "").lstrip().casefold()
    return text.startswith("{") or text.startswith("```json") or "<function" in text


def visible_reply(raw_text: str, decoded_reply: str | None = None) -> str:
    """Return only user-visible prose, rejecting undecodable private transport output."""
    decoded = decoded_reply if decoded_reply is not None else structured_companion_reply(raw_text)
    if decoded:
        return decoded
    if looks_like_model_transport(raw_text):
        raise AgentProviderError("Model returned an undecodable private response envelope.")
    return str(raw_text or "").strip()


__all__ = ["looks_like_model_transport", "visible_reply"]
