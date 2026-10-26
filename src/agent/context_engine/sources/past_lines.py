"""Real past lines that may answer this message, found by code before every reply."""

from __future__ import annotations

from typing import Any

PAST_LINES_SOURCE_TYPE = "past_lines"


def past_lines_sources(
    user_id: str | None,
    conversation_id: str,
    user_text: str,
    query_embedding: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Real past lines that may answer this message, found by code before every reply."""
    if not user_id:
        return []
    # Imported here: search reaches the providers, which import this module.
    from agent.memory_engine.search import recall_lines, recall_note

    try:
        hits = recall_lines(user_id, user_text, query_embedding, conversation_id=conversation_id)
    except Exception:  # recall is a bonus; the reply goes on without it
        return []
    if not hits:
        return []
    return [{"source_type": PAST_LINES_SOURCE_TYPE, "title": "Lines from earlier chats", "content": recall_note(hits), "metadata": {"hits": len(hits)}}]


__all__ = ["PAST_LINES_SOURCE_TYPE", "past_lines_sources"]
