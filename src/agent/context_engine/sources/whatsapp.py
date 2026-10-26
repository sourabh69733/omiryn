"""Older chunk retrieval from parsed WhatsApp imports. In v3 it serves only a friend's style the
user chose for Omi to copy; their own uploads reach replies through shared_chats and search."""

from __future__ import annotations

from typing import Any

from agent.context_engine.contracts.models import ContextQueryIntent
from agent.context_engine.personalization import style_adaptation_guide
from agent.context_engine.understanding.rules.intent import RECENCY_QUERY_TERMS
from agent.context_engine.shared.text import memory_terms, normalized_memory_text, source_identity
from agent.memory_engine.data_points.retrieval.whatsapp import retrieve_whatsapp_imports, retrieve_whatsapp_memory
from text_vectors import build_text_embedding, cosine_similarity

from .attached import STYLE_CONTEXT_SOURCE_TYPES, should_retrieve_memory

WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT = 2
WHATSAPP_FUEL_RETRIEVAL_LIMIT = 1
WHATSAPP_STRUCTURED_SOURCE_TYPE = "whatsapp_structured_context"


def structured_whatsapp_sources(
    all_sources: list[dict[str, Any]],
    attached_sources: list[dict[str, Any]],
    selected_styles: list[dict[str, Any]],
    user_text: str,
    user_id: str | None,
    query_intent: ContextQueryIntent,
) -> list[dict[str, Any]]:
    conversation_fuel = _should_retrieve_whatsapp_conversation_fuel(user_text)
    should_retrieve = should_retrieve_memory(user_text)
    if not should_retrieve and not conversation_fuel:
        return []

    source_ids = _active_whatsapp_context_source_ids(all_sources, attached_sources, selected_styles)
    if not source_ids:
        return []

    imports = [
        item
        for item in retrieve_whatsapp_imports(user_id=user_id)
        if str(item.get("context_source_id")) in source_ids
    ]
    if not imports:
        return []

    sources = [
        source
        for source in (
            _structured_whatsapp_context_source(
                item,
                user_text,
                user_id,
                conversation_fuel=conversation_fuel and not query_intent.prefer_structured_whatsapp,
            )
            for item in imports
        )
        if source
    ]
    return [_with_query_intent(source, query_intent) for source in sources]


def own_upload(source: dict[str, Any]) -> bool:
    """A WhatsApp chat of the user's own (not a friend's style to copy)."""
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    return source.get("source_type") == "whatsapp_chat" and (metadata.get("style_kind") or "user_style") == "user_style"


def _active_whatsapp_context_source_ids(
    all_sources: list[dict[str, Any]],
    attached_sources: list[dict[str, Any]],
    selected_styles: list[dict[str, Any]],
) -> set[str]:
    source_ids = {
        source_identity(source)
        for source in selected_styles
        if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    }
    source_ids.update(
        source_identity(source)
        for source in attached_sources
        if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    )
    source_ids.update(
        source_identity(source)
        for source in all_sources
        if source.get("source_type") in STYLE_CONTEXT_SOURCE_TYPES
    )
    return {source_id for source_id in source_ids if source_id}


def _structured_whatsapp_context_source(
    whatsapp_import: dict[str, Any],
    user_text: str,
    user_id: str | None,
    *,
    conversation_fuel: bool = False,
) -> dict[str, Any] | None:
    import_id = str(whatsapp_import["id"])
    memory = retrieve_whatsapp_memory(import_id, user_id)
    chunks = memory["chunks"]
    people = memory["people"]
    style_profiles = memory["style_profiles"]
    if not chunks and not style_profiles and not people:
        return None

    selected_sender = str(whatsapp_import.get("selected_sender") or "")
    ranked_chunks = _rank_whatsapp_chunks(chunks, user_text)
    chunk_limit = (
        WHATSAPP_FUEL_RETRIEVAL_LIMIT if conversation_fuel else WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT
    )
    content = _structured_whatsapp_context_text(
        whatsapp_import,
        people,
        style_profiles,
        ranked_chunks[:chunk_limit],
        selected_sender,
        conversation_fuel=conversation_fuel,
    )
    return {
        "source_type": WHATSAPP_STRUCTURED_SOURCE_TYPE,
        "title": f"Structured WhatsApp context: {whatsapp_import.get('title') or 'import'}",
        "content": content,
        "metadata": {
            "context_source_id": whatsapp_import.get("context_source_id"),
            "import_id": import_id,
            "selected_sender": selected_sender,
            "retrieved_chunk_count": min(len(ranked_chunks), chunk_limit),
            "conversation_fuel": conversation_fuel,
        },
    }


def _with_query_intent(
    source: dict[str, Any],
    query_intent: ContextQueryIntent,
) -> dict[str, Any]:
    if not query_intent.labels:
        return source
    metadata = dict(source.get("metadata") or {})
    metadata["query_intent"] = list(query_intent.labels)
    return {**source, "metadata": metadata}


def _structured_whatsapp_context_text(
    whatsapp_import: dict[str, Any],
    people: list[dict[str, Any]],
    style_profiles: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    selected_sender: str,
    *,
    conversation_fuel: bool = False,
) -> str:
    sections = [
        "Structured WhatsApp context.",
        "Use this when the user asks about uploaded WhatsApp chat, people, topics, messages, or texting style.",
        "When marked as conversation fuel, use one small topic or recent event to continue naturally.",
        "Do not claim live WhatsApp access; answer from this stored parsed import.",
        f"Import title: {whatsapp_import.get('title') or '-'}",
        f"Selected sender: {selected_sender or '-'}",
        f"Mode: {'conversation fuel' if conversation_fuel else 'direct retrieval'}",
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
        selected_profiles = _ordered_style_profiles(style_profiles, selected_sender)
        sections.extend(["", "Style adaptation guides:"])
        for profile in selected_profiles[:2]:
            sections.append(
                style_adaptation_guide(
                    profile,
                    selected=str(profile.get("sender") or "").casefold()
                    == selected_sender.casefold(),
                )
            )
        sections.extend(["", "Sender style profile metrics:"])
        for profile in selected_profiles[:4]:
            summary = profile.get("summary") or {}
            terms = ", ".join(summary.get("topic_terms") or summary.get("frequent_terms") or [])
            samples = "; ".join(
                str(sample) for sample in (profile.get("sample_messages") or [])[:3]
            )
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


def _should_retrieve_whatsapp_conversation_fuel(user_text: str) -> bool:
    terms = memory_terms(user_text)
    if not terms:
        return False
    if len(terms) <= 4 and not should_retrieve_memory(user_text):
        return False
    normalized = normalized_memory_text(user_text)
    return normalized in {
        "batao",
        "tell",
        "continue from whatsapp",
        "continue from uploaded chat",
        "uploaded chat se batao",
        "whatsapp se batao",
    }


def _ordered_style_profiles(
    style_profiles: list[dict[str, Any]],
    selected_sender: str,
) -> list[dict[str, Any]]:
    if not selected_sender:
        return style_profiles
    selected_casefold = selected_sender.casefold()
    return sorted(
        style_profiles,
        key=lambda profile: (
            str(profile.get("sender") or "").casefold() != selected_casefold,
            str(profile.get("sender") or ""),
        ),
    )


def _rank_whatsapp_chunks(
    chunks: list[dict[str, Any]],
    user_text: str,
) -> list[dict[str, Any]]:
    query_terms = memory_terms(user_text)
    query_embedding = build_text_embedding(user_text, query_terms)
    if not query_terms:
        return chunks[-WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT:]

    max_index = max((int(chunk.get("chunk_index") or 0) for chunk in chunks), default=1)
    wants_recent = bool(query_terms & RECENCY_QUERY_TERMS)
    scored_chunks = [
        (score, chunk)
        for chunk in chunks
        for score in [
            _whatsapp_chunk_score(
                chunk,
                query_terms,
                query_embedding,
                max_index,
                wants_recent,
            )
        ]
    ]
    scored_chunks.sort(
        key=lambda item: (
            item[0],
            int(item[1].get("chunk_index") or 0),
        ),
        reverse=True,
    )
    positive_chunks = [chunk for score, chunk in scored_chunks if score > 0.05]
    return positive_chunks or chunks[-WHATSAPP_STRUCTURED_RETRIEVAL_LIMIT:]


def _whatsapp_chunk_score(
    chunk: dict[str, Any],
    query_terms: set[str],
    query_embedding: dict[str, Any],
    max_index: int,
    wants_recent: bool,
) -> float:
    chunk_text = normalized_memory_text(
        " ".join(
            [
                str(chunk.get("content") or ""),
                " ".join(str(term) for term in chunk.get("terms") or []),
            ]
        )
    )
    lexical_score = sum(1 for term in query_terms if term in chunk_text)
    semantic_score = cosine_similarity(query_embedding, chunk.get("embedding"))
    recency_score = (int(chunk.get("chunk_index") or 0) / max(1, max_index)) if max_index else 0
    recency_weight = 1.25 if wants_recent else 0.15
    return (semantic_score * 6) + lexical_score + (recency_score * recency_weight)


__all__ = ["WHATSAPP_STRUCTURED_SOURCE_TYPE", "own_upload", "structured_whatsapp_sources"]
