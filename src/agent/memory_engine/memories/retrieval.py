"""Selects a small, safe set of canonical memories for one companion reply."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from .models import MemoryKind, MemorySensitivity, MemoryStatus, MemoryUse
from .ranking import (
    aware_datetime,
    bounded_score,
    embedding_similarity,
    recency_score,
    searchable_memory_text,
    text_relevance,
)


DEFAULT_REPLY_MEMORY_LIMIT = 5
_KIND_LIMITS = {
    MemoryKind.SEMANTIC.value: 2,
    MemoryKind.EPISODIC.value: 1,
    MemoryKind.RELATIONSHIP.value: 1,
    MemoryKind.PROCEDURAL.value: 1,
}


def retrieve_agent_memories_for_reply(
    user_id: str,
    user_text: str,
    *,
    limit: int = DEFAULT_REPLY_MEMORY_LIMIT,
    now: datetime | None = None,
    query_embedding: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return active reply-safe memories ranked without another model call."""
    if limit <= 0:
        return []
    # Local import avoids coupling storage initialization to retrieval policy.
    from storage.memory_embeddings import list_agent_memory_embeddings
    from storage.memories import list_agent_memories

    current_time = now or datetime.now(UTC)
    eligible = [
        memory
        for memory in list_agent_memories(user_id)
        if _reply_eligible(memory, current_time)
    ]
    embeddings = (
        list_agent_memory_embeddings(
            user_id,
            [str(memory["id"]) for memory in eligible],
        )
        if query_embedding
        else []
    )
    embeddings_by_memory_id = {str(item["memory_id"]): item for item in embeddings}
    ranked = sorted(
        eligible,
        key=lambda memory: (
            -_reply_score(
                memory,
                user_text,
                current_time,
                query_embedding=query_embedding,
                memory_embedding=embeddings_by_memory_id.get(str(memory.get("id") or "")),
            ),
            str(memory.get("id") or ""),
        ),
    )
    selected: list[dict[str, Any]] = []
    kind_counts: dict[str, int] = defaultdict(int)
    for memory in ranked:
        kind = str(memory.get("kind") or "")
        if kind_counts[kind] >= _KIND_LIMITS.get(kind, 0):
            continue
        selected.append(memory)
        kind_counts[kind] += 1
        if len(selected) >= limit:
            break
    return selected


def _reply_eligible(memory: dict[str, Any], now: datetime) -> bool:
    return (
        _is_not_expired(memory.get("valid_until"), now)
        and memory.get("status") == MemoryStatus.ACTIVE.value
        and MemoryUse.REPLY_CONTEXT.value in set(memory.get("allowed_uses") or [])
        and memory.get("sensitivity") != MemorySensitivity.HIGHLY_SENSITIVE.value
        and memory.get("kind") in _KIND_LIMITS
    )


def _is_not_expired(value: Any, now: datetime) -> bool:
    if value is None:
        return True
    expires_at = aware_datetime(value)
    return expires_at is not None and now < expires_at



def _reply_score(
    memory: dict[str, Any],
    user_text: str,
    now: datetime,
    *,
    query_embedding: dict[str, Any] | None = None,
    memory_embedding: dict[str, Any] | None = None,
) -> float:
    lexical_relevance = text_relevance(user_text, searchable_memory_text(memory))
    semantic_relevance = embedding_similarity(query_embedding, memory_embedding)
    relevance = (
        lexical_relevance
        if semantic_relevance is None
        else semantic_relevance * 0.75 + lexical_relevance * 0.25
    )
    procedural_priority = (
        0.1 if memory.get("kind") == MemoryKind.PROCEDURAL.value else 0.0
    )
    return (
        relevance * 0.55
        + bounded_score(memory.get("confidence")) * 0.2
        + bounded_score(memory.get("importance")) * 0.15
        + recency_score(memory.get("updated_at"), now) * 0.1
        + procedural_priority
    )


__all__ = ["DEFAULT_REPLY_MEMORY_LIMIT", "retrieve_agent_memories_for_reply"]
