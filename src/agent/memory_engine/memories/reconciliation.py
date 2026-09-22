"""Selects bounded existing-memory context for V3 lifecycle reconciliation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.shared.clock import utc_now
from .models import MemoryStatus
from .ranking import (
    bounded_score,
    embedding_similarity,
    recency_score,
    searchable_memory_text,
    text_relevance,
)


def select_reconciliation_candidates(
    memories: list[dict[str, Any]],
    user_text: str,
    *,
    limit: int = 8,
    now: datetime | None = None,
    query_embedding: dict[str, Any] | None = None,
    embeddings_by_memory_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return related active memories and inactive lifecycle history."""
    if limit <= 0:
        return []
    current_time = now or utc_now()
    lifecycle_statuses = {
        MemoryStatus.ACTIVE.value,
        MemoryStatus.RETRACTED.value,
        MemoryStatus.SUPERSEDED.value,
    }
    eligible = [memory for memory in memories if memory.get("status") in lifecycle_statuses]
    return sorted(
        eligible,
        key=lambda memory: (
            -_reconciliation_score(
                memory,
                user_text,
                current_time,
                query_embedding=query_embedding,
                memory_embedding=(embeddings_by_memory_id or {}).get(
                    str(memory.get("id") or "")
                ),
            ),
            str(memory.get("id") or ""),
        ),
    )[:limit]


def _reconciliation_score(
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
    return (
        relevance * 0.7
        + bounded_score(memory.get("importance")) * 0.15
        + bounded_score(memory.get("confidence")) * 0.1
        + recency_score(memory.get("updated_at"), now) * 0.05
    )


__all__ = ["select_reconciliation_candidates"]
