from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from storage import (
    list_context_sources,
    list_user_context_sources,
    list_whatsapp_chunks,
    list_whatsapp_imports,
    list_whatsapp_people,
    list_whatsapp_style_profiles,
)

STYLE_CONTEXT_SOURCE_TYPES = {"whatsapp_chat", "friend_style"}
MEMORY_RETRIEVAL_LIMIT = 2
WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT = 2
WHATSAPP_STRUCTURED_SOURCE_TYPE = "whatsapp_structured_context"
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
    all_sources = list_context_sources(conversation_id, user_id)
    attached_sources = _valid_attached_context_sources(all_sources, user_id)
    selected_styles = _selected_style_sources(all_sources, style_source_id)
    retrieved_sources = _relevant_memory_sources(attached_sources, user_text)
    structured_whatsapp_sources = _structured_whatsapp_context_sources(
        all_sources,
        attached_sources,
        selected_styles,
        user_text,
        user_id,
    )

    if selected_styles:
        selected_style_ids = {_source_identity(source) for source in selected_styles}
        return selected_styles + structured_whatsapp_sources + [
            source for source in retrieved_sources if _source_identity(source) not in selected_style_ids
        ]

    return structured_whatsapp_sources + retrieved_sources


def build_profile_extraction_context_sources(
    conversation_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        source
        for source in _valid_attached_context_sources(
            list_context_sources(conversation_id, user_id),
            user_id,
        )
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
        _source_matches_id(source, style_source_id)
        and source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
        for source in list_context_sources(conversation_id, user_id)
    )


def _valid_attached_context_sources(
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


def _selected_style_sources(
    sources: list[dict[str, Any]],
    style_source_id: str | None,
) -> list[dict[str, Any]]:
    style_sources = [
        source for source in sources if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    ]
    if not style_source_id:
        return []
    selected = [source for source in style_sources if _source_matches_id(source, style_source_id)]
    return selected


def _source_matches_id(source: dict[str, Any], source_id: str | None) -> bool:
    if not source_id:
        return False
    return _source_identity(source) == source_id or source.get("id") == source_id


def _source_identity(source: dict[str, Any]) -> str:
    metadata = source.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("original_source_id"):
        return str(metadata["original_source_id"])
    return str(source.get("id") or "")


def _structured_whatsapp_context_sources(
    all_sources: list[dict[str, Any]],
    attached_sources: list[dict[str, Any]],
    selected_styles: list[dict[str, Any]],
    user_text: str,
    user_id: str | None,
) -> list[dict[str, Any]]:
    if not selected_styles and not _should_retrieve_memory(user_text):
        return []

    source_ids = _active_whatsapp_context_source_ids(all_sources, attached_sources, selected_styles)
    if not source_ids:
        return []

    imports = [
        item
        for item in list_whatsapp_imports(user_id=user_id)
        if str(item.get("context_source_id")) in source_ids
    ]
    if not imports:
        return []

    return [
        source
        for source in (
            _structured_whatsapp_context_source(item, user_text, user_id)
            for item in imports
        )
        if source
    ]


def _active_whatsapp_context_source_ids(
    all_sources: list[dict[str, Any]],
    attached_sources: list[dict[str, Any]],
    selected_styles: list[dict[str, Any]],
) -> set[str]:
    source_ids = {
        _source_identity(source)
        for source in selected_styles
        if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    }
    source_ids.update(
        _source_identity(source)
        for source in attached_sources
        if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    )
    source_ids.update(
        _source_identity(source)
        for source in all_sources
        if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    )
    return {source_id for source_id in source_ids if source_id}


def _structured_whatsapp_context_source(
    whatsapp_import: dict[str, Any],
    user_text: str,
    user_id: str | None,
) -> dict[str, Any] | None:
    import_id = str(whatsapp_import["id"])
    chunks = list_whatsapp_chunks(import_id, user_id)
    people = list_whatsapp_people(import_id, user_id)
    style_profiles = list_whatsapp_style_profiles(import_id, user_id)
    if not chunks and not style_profiles and not people:
        return None

    selected_sender = str(whatsapp_import.get("selected_sender") or "")
    ranked_chunks = _rank_whatsapp_chunks(chunks, user_text)
    content = _structured_whatsapp_context_text(
        whatsapp_import,
        people,
        style_profiles,
        ranked_chunks[:WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT],
        selected_sender,
    )
    return {
        "source_type": WHATSAPP_STRUCTURED_SOURCE_TYPE,
        "title": f"Structured WhatsApp context: {whatsapp_import.get('title') or 'import'}",
        "content": content,
        "metadata": {
            "context_source_id": whatsapp_import.get("context_source_id"),
            "import_id": import_id,
            "selected_sender": selected_sender,
            "retrieved_chunk_count": min(len(ranked_chunks), WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT),
        },
    }


def _structured_whatsapp_context_text(
    whatsapp_import: dict[str, Any],
    people: list[dict[str, Any]],
    style_profiles: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    selected_sender: str,
) -> str:
    sections = [
        "Structured WhatsApp context.",
        "Use this when the user asks about uploaded WhatsApp chat, people, topics, messages, or texting style.",
        "Do not claim live WhatsApp access; answer from this stored parsed import.",
        f"Import title: {whatsapp_import.get('title') or '-'}",
        f"Selected sender: {selected_sender or '-'}",
    ]
    if people:
        sections.extend(
            [
                "",
                "People:",
                *[
                    f"- {person['sender']} ({person['role']}): {person['message_count']} messages"
                    for person in people[:6]
                ],
            ]
        )
    if style_profiles:
        sections.extend(["", "Sender style profiles:"])
        for profile in style_profiles[:4]:
            summary = profile.get("summary") or {}
            terms = ", ".join(summary.get("topic_terms") or summary.get("frequent_terms") or [])
            samples = "; ".join(str(sample) for sample in (profile.get("sample_messages") or [])[:3])
            sections.append(
                "- "
                f"{profile['sender']}: avg_words={summary.get('average_words')}; "
                f"short={summary.get('short_message_share')}; "
                f"questions={summary.get('question_share')}; "
                f"topics={terms or 'not enough signal'}; "
                f"samples={samples or 'not enough signal'}"
            )
    if chunks:
        sections.extend(["", "Relevant message chunks:"])
        for chunk in chunks:
            sections.append(str(chunk.get("content") or ""))
    return "\n".join(sections)


def _rank_whatsapp_chunks(
    chunks: list[dict[str, Any]],
    user_text: str,
) -> list[dict[str, Any]]:
    query_terms = _memory_terms(user_text)
    if not query_terms:
        return chunks[:WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT]
    scored_chunks = [
        (score, chunk)
        for chunk in chunks
        for score in [_whatsapp_chunk_score(chunk, query_terms)]
    ]
    scored_chunks.sort(
        key=lambda item: (
            item[0],
            int(item[1].get("chunk_index") or 0),
        ),
        reverse=True,
    )
    positive_chunks = [chunk for score, chunk in scored_chunks if score > 0]
    return positive_chunks or chunks[-WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT:]


def _whatsapp_chunk_score(chunk: dict[str, Any], query_terms: set[str]) -> int:
    chunk_text = _normalized_memory_text(
        " ".join(
            [
                str(chunk.get("content") or ""),
                " ".join(str(term) for term in chunk.get("terms") or []),
            ]
        )
    )
    return sum(chunk_text.count(term) for term in query_terms)


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
