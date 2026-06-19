from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from storage import list_context_sources

STYLE_CONTEXT_SOURCE_TYPES = {"whatsapp_chat", "friend_style"}
MEMORY_RETRIEVAL_LIMIT = 2
MEMORY_TRIGGER_TERMS = {
    "context",
    "memory",
    "remember",
    "saved",
    "imported",
    "upload",
    "uploaded",
    "whatsapp",
    "chatgpt",
    "claude",
    "gemini",
    "summary",
    "profile",
    "about me",
    "know about me",
    "what do you know",
    "last topic",
    "last message",
    "past chat",
    "conversation",
}


@dataclass(frozen=True)
class AgentContext:
    user_profile: dict[str, Any] | None = None
    context_sources: list[dict[str, Any]] = field(default_factory=list)


def build_reply_context(
    conversation_id: str,
    user_text: str,
    *,
    user_id: str | None = None,
    user_profile: dict[str, Any] | None = None,
    style_source_id: str | None = None,
) -> AgentContext:
    return AgentContext(
        user_profile=user_profile,
        context_sources=build_reply_context_sources(
            conversation_id,
            style_source_id,
            user_text,
            user_id,
        ),
    )


def build_reply_context_sources(
    conversation_id: str,
    style_source_id: str | None,
    user_text: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    sources = list_context_sources(conversation_id, user_id)
    selected_styles = _selected_style_sources(sources, style_source_id)
    retrieved_sources = _relevant_memory_sources(sources, user_text)

    if selected_styles:
        selected_style_ids = {source.get("id") for source in selected_styles}
        return selected_styles + [
            source for source in retrieved_sources if source.get("id") not in selected_style_ids
        ]

    return retrieved_sources


def build_profile_extraction_context_sources(
    conversation_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        source
        for source in list_context_sources(conversation_id, user_id)
        if source.get("source_type") not in STYLE_CONTEXT_SOURCE_TYPES
    ]


def selected_style_source_exists(
    conversation_id: str,
    style_source_id: str | None,
    user_id: str | None = None,
) -> bool:
    if not style_source_id:
        return True
    return any(
        source.get("id") == style_source_id
        and source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
        for source in list_context_sources(conversation_id, user_id)
    )


def _selected_style_sources(
    sources: list[dict[str, Any]],
    style_source_id: str | None,
) -> list[dict[str, Any]]:
    style_sources = [
        source for source in sources if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    ]
    if not style_source_id:
        return style_sources[:MEMORY_RETRIEVAL_LIMIT]
    selected = [source for source in style_sources if source.get("id") == style_source_id]
    return selected or style_sources[:MEMORY_RETRIEVAL_LIMIT]


def _relevant_memory_sources(
    sources: list[dict[str, Any]],
    user_text: str,
) -> list[dict[str, Any]]:
    if not _should_retrieve_memory(user_text):
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


def _should_retrieve_memory(user_text: str) -> bool:
    normalized = _normalized_memory_text(user_text)
    return any(term in normalized for term in MEMORY_TRIGGER_TERMS)


def _memory_source_score(source: dict[str, Any], user_text: str) -> int:
    query_terms = _memory_terms(user_text)
    if not query_terms:
        return 0
    source_text = _normalized_memory_text(
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


def _memory_terms(text: str) -> set[str]:
    normalized = _normalized_memory_text(text)
    stop_words = {
        "the",
        "and",
        "for",
        "you",
        "your",
        "about",
        "with",
        "from",
        "what",
        "that",
        "this",
        "tell",
        "me",
        "my",
        "can",
        "please",
    }
    return {term for term in normalized.split() if len(term) >= 3 and term not in stop_words}


def _normalized_memory_text(text: str) -> str:
    return " ".join(
        "".join(character.lower() if character.isalnum() else " " for character in text).split()
    )
