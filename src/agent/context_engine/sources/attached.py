"""Sources the user attached to a chat (notes, profiles, style chats): which are valid, which style
is selected, and which notes a message asks about."""

from __future__ import annotations

from typing import Any

from agent.context_engine.shared.text import memory_terms, normalized_memory_text, source_identity
from storage import list_user_context_sources

STYLE_CONTEXT_SOURCE_TYPES = {"whatsapp_chat", "friend_style"}
MEMORY_RETRIEVAL_LIMIT = 2
MEMORY_TRIGGER_TERMS = {
    "chat",
    "context",
    "message",
    "messages",
    "memory",
    "remember",
    "saved",
    "style",
    "talk",
    "talking",
    "topics",
    "topic",
    "tone",
    "imported",
    "upload",
    "uploaded",
    "way",
    "whatsapp",
    "chatgpt",
    "claude",
    "gemini",
    "summary",
    "profile",
    "convo",
    "msg",
    "about me",
    "know about me",
    "what do you know",
    "last topic",
    "last message",
    "past chat",
    "conversation",
}
MEMORY_TRIGGER_PHRASES = {
    "kaise baat",
    "kaise text",
    "kaise bol",
    "kis style",
    "kya baat",
    "kya baate",
    "hum kya",
    "last convo",
    "pichli baat",
    "pehle kya",
    "previous chat",
    "uploaded chat",
    "where did",
    "whatsapp chat",
}


def valid_attached_sources(
    sources: list[dict[str, Any]],
    user_id: str | None,
) -> list[dict[str, Any]]:
    reusable_source_ids = {
        str(source["id"])
        for source in list_user_context_sources(user_id)
        if not (
            isinstance(source.get("metadata"), dict)
            and source["metadata"].get("original_source_id")
        )
    }
    return [
        source
        for source in sources
        if isinstance(source.get("metadata"), dict)
        and source["metadata"].get("original_source_id")
        and str(source["metadata"].get("original_source_id")) in reusable_source_ids
    ]


def selected_style_sources(
    sources: list[dict[str, Any]],
    style_source_id: str | None,
) -> list[dict[str, Any]]:
    style_sources = [
        source for source in sources if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    ]
    if not style_source_id:
        return []
    selected = [source for source in style_sources if source_matches_id(source, style_source_id)]
    return selected


def source_matches_id(source: dict[str, Any], source_id: str | None) -> bool:
    if not source_id:
        return False
    return source_identity(source) == source_id or source.get("id") == source_id


def relevant_attached_sources(
    sources: list[dict[str, Any]],
    user_text: str,
) -> list[dict[str, Any]]:
    if not should_retrieve_memory(user_text):
        return []

    scored_sources = [
        (score, source)
        for source in sources
        if source.get("source_type") not in STYLE_CONTEXT_SOURCE_TYPES
        for score in [_memory_source_score(source, user_text)]
        if score > 0
    ]
    scored_sources.sort(key=lambda item: item[0], reverse=True)
    return [source for _, source in scored_sources[:MEMORY_RETRIEVAL_LIMIT]]


def should_retrieve_memory(user_text: str) -> bool:
    normalized = normalized_memory_text(user_text)
    return any(term in normalized for term in MEMORY_TRIGGER_TERMS) or any(
        phrase in normalized for phrase in MEMORY_TRIGGER_PHRASES
    )


def _memory_source_score(source: dict[str, Any], user_text: str) -> int:
    query_terms = memory_terms(user_text)
    if not query_terms:
        return 0
    source_text = normalized_memory_text(
        " ".join(
            [
                str(source.get("title") or ""),
                str(source.get("source_type") or ""),
                str(source.get("content") or ""),
            ]
        )
    )
    score = sum(source_text.count(term) for term in query_terms)
    source_type = source.get("source_type")
    if source_type == "llm_profile" and any(
        term in query_terms for term in {"profile", "about", "me"}
    ):
        score += 2
    if source_type == "chat_export" and any(
        term in query_terms for term in {"chat", "conversation", "topic"}
    ):
        score += 2
    return score


__all__ = ["STYLE_CONTEXT_SOURCE_TYPES", "relevant_attached_sources", "selected_style_sources", "should_retrieve_memory", "source_matches_id", "valid_attached_sources"]
