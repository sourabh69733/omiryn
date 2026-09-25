"""Selects a small, safe set of canonical memories for one companion reply."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from typing import Any

from agent.shared.clock import utc_now
from .models import MemoryKind, MemorySensitivity, MemoryStatus, MemoryUse
from .ranking import (
    aware_datetime,
    bounded_score,
    embedding_similarity,
    recency_score,
    searchable_memory_text,
    text_relevance,
)


DEFAULT_REPLY_MEMORY_LIMIT = int(os.getenv("AGENT_REPLY_MEMORY_LIMIT", "8"))
# "What do you know about me?" wants the whole picture, not only what matches its words.
BROAD_RECALL_MEMORY_LIMIT = int(os.getenv("AGENT_BROAD_RECALL_MEMORY_LIMIT", "12"))
# Quality metadata may rank candidates, but only query relevance admits content memories.
_LEXICAL_RELEVANCE_FLOOR = 0.05
# Calibrated on bge-m3 (retrieval case eval, 2026-09-20): related memories scored 0.48-0.63,
# unrelated ones up to 0.44. The margin is thin, so re-check when the model or fixtures change.
_SEMANTIC_RELEVANCE_FLOOR = 0.45
# One total budget; the per-kind cap only stops a single kind from filling every slot.
_KIND_LIMITS = {
    MemoryKind.SEMANTIC.value: 5,
    MemoryKind.EPISODIC.value: 5,
    MemoryKind.RELATIONSHIP.value: 4,
    MemoryKind.PROCEDURAL.value: 3,
}


def retrieve_agent_memories_for_reply(
    user_id: str,
    user_text: str,
    *,
    limit: int = DEFAULT_REPLY_MEMORY_LIMIT,
    now: datetime | None = None,
    query_embedding: dict[str, Any] | None = None,
    broad: bool = False,
) -> list[dict[str, Any]]:
    """Return active reply-safe memories ranked without another model call.

    `broad` is for questions about the user as a whole: no relevance floor, so the most
    important and confident memories come back even when they share no words with the query.
    """
    if limit <= 0:
        return []
    # Local import avoids coupling storage initialization to retrieval policy.
    from storage.memory_embeddings import list_agent_memory_embeddings
    from storage.memories import list_agent_memories

    current_time = now or utc_now()
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
        (
            (
                memory,
                *_calculate_reply_relevance(
                    memory,
                    user_text,
                    query_embedding=query_embedding,
                    memory_embedding=embeddings_by_memory_id.get(
                        str(memory.get("id") or "")
                    ),
                ),
            )
            for memory in eligible
        ),
        key=lambda item: (
            -_reply_score(
                item[0],
                current_time,
                lexical_relevance=item[1],
                semantic_relevance=item[2],
            ),
            str(item[0].get("id") or ""),
        ),
    )
    selected: list[dict[str, Any]] = []
    kind_counts: dict[str, int] = defaultdict(int)
    for memory, lexical_relevance, semantic_relevance in ranked:
        kind = str(memory.get("kind") or "")
        if not broad and kind != MemoryKind.PROCEDURAL.value and not _meets_relevance_threshold(
            lexical_relevance,
            semantic_relevance,
        ):
            continue
        if kind_counts[kind] >= _KIND_LIMITS.get(kind, 0):
            continue
        selected.append(memory)
        kind_counts[kind] += 1
        if len(selected) >= limit:
            break
    return selected


def _reply_eligible(memory: dict[str, Any], now: datetime) -> bool:
    return (
        _is_current(memory.get("valid_from"), memory.get("valid_until"), now)
        and memory.get("status") == MemoryStatus.ACTIVE.value
        and MemoryUse.REPLY_CONTEXT.value in set(memory.get("allowed_uses") or [])
        and memory.get("sensitivity") != MemorySensitivity.HIGHLY_SENSITIVE.value
        and memory.get("kind") in _KIND_LIMITS
    )


def _is_current(valid_from: Any, valid_until: Any, now: datetime) -> bool:
    starts_at = aware_datetime(valid_from) if valid_from is not None else None
    expires_at = aware_datetime(valid_until) if valid_until is not None else None
    if valid_from is not None and starts_at is None:
        return False
    if valid_until is not None and expires_at is None:
        return False
    return (starts_at is None or starts_at <= now) and (
        expires_at is None or now < expires_at
    )

def _reply_score(
    memory: dict[str, Any],
    now: datetime,
    *,
    lexical_relevance: float,
    semantic_relevance: float | None,
) -> float:
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


def _calculate_reply_relevance(
    memory: dict[str, Any],
    user_text: str,
    *,
    query_embedding: dict[str, Any] | None,
    memory_embedding: dict[str, Any] | None,
) -> tuple[float, float | None]:
    """
    calculates how closely a memory relates to the current user message:

    - Lexical relevance: shared words/text.
    - Semantic relevance: embedding similarity.
    """
    return (
        text_relevance(user_text, searchable_memory_text(memory)),
        embedding_similarity(query_embedding, memory_embedding),
    )


def _meets_relevance_threshold(
    lexical_relevance: float,
    semantic_relevance: float | None,
) -> bool:
    """
    It checks whether either score is high enough to include that memory in the prompt.

    Flow:

    calculate relevance -> reject unrelated memory -> rank accepted memories

    Without the gate, an unrelated memory could still be selected merely because it ranked highest among poor candidates.

    The names are slightly repetitive. Clearer names would be:
    """
    return lexical_relevance >= _LEXICAL_RELEVANCE_FLOOR or (
        semantic_relevance is not None
        and semantic_relevance >= _SEMANTIC_RELEVANCE_FLOOR
    )


__all__ = ["DEFAULT_REPLY_MEMORY_LIMIT", "retrieve_agent_memories_for_reply"]
