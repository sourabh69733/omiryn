from __future__ import annotations

from typing import Any

WHATSAPP_CONTEXT_SOURCE_TYPE = "whatsapp_structured_context"


def whatsapp_usage_prompt(context_sources: list[dict[str, Any]] | None) -> str:
    if not _has_whatsapp_context(context_sources):
        return ""
    return """WhatsApp context usage:
- If structured WhatsApp context is present, treat it as a stored parsed import the user attached.
- You may use its topics, recent events, people, and style hints to continue the conversation naturally.
- If the user is quiet or gives a short reply, pick one small topic from the attached chat.
- Do not say you have no access to WhatsApp when this context is present.
- Say "from your uploaded chat" if you need to clarify where the information came from.
- Do not impersonate the real chat partner or claim they currently feel, approve, or said anything.
- Adapt tone lightly from the style guide; do not copy private messages word-for-word unless asked."""


def _has_whatsapp_context(context_sources: list[dict[str, Any]] | None) -> bool:
    return any(
        source.get("source_type") == WHATSAPP_CONTEXT_SOURCE_TYPE
        for source in context_sources or []
    )
