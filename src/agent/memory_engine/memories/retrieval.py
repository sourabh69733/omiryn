"""Selects a small, safe set of canonical memories for one companion reply."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from .models import MemoryKind, MemorySensitivity, MemoryStatus, MemoryUse


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
) -> list[dict[str, Any]]:
    """Return active reply-safe memories ranked without another model call."""
    if limit <= 0:
        return []
    # Local import avoids coupling storage initialization to retrieval policy.
    from storage.memories import list_agent_memories

    current_time = now or datetime.now(UTC)
    eligible = [
        memory
        for memory in list_agent_memories(user_id)
        if _reply_eligible(memory, current_time)
    ]
    ranked = sorted(
        eligible,
        key=lambda memory: (
            -_reply_score(memory, user_text, current_time),
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
    expires_at = _aware_datetime(value)
    return expires_at is not None and now < expires_at


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _reply_score(memory: dict[str, Any], user_text: str, now: datetime) -> float:
    relevance = _text_relevance(user_text, _searchable_text(memory))
    confidence = _bounded_score(memory.get("confidence"))
    importance = _bounded_score(memory.get("importance"))
    recency = _recency_score(memory.get("updated_at"), now)
    procedural_priority = 0.1 if memory.get("kind") == MemoryKind.PROCEDURAL.value else 0.0
    return (
        relevance * 0.55
        + confidence * 0.2
        + importance * 0.15
        + recency * 0.1
        + procedural_priority
    )


def _searchable_text(memory: dict[str, Any]) -> str:
    return " ".join(
        (
            str(memory.get("key") or ""),
            json.dumps(memory.get("value"), ensure_ascii=False, sort_keys=True),
            " ".join(str(value) for value in memory.get("purposes") or []),
        )
    )


def _text_relevance(query: str, candidate: str) -> float:
    query_tokens = set(_tokens(query))
    candidate_tokens = set(_tokens(candidate))
    token_score = (
        len(query_tokens & candidate_tokens) / math.sqrt(len(query_tokens) * len(candidate_tokens))
        if query_tokens and candidate_tokens
        else 0.0
    )
    query_grams = _character_ngrams(query)
    candidate_grams = _character_ngrams(candidate)
    gram_score = (
        len(query_grams & candidate_grams) / len(query_grams | candidate_grams)
        if query_grams and candidate_grams
        else 0.0
    )
    return max(token_score, gram_score)


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[\w']+", value.casefold()) if len(token) >= 2]


def _character_ngrams(value: str, size: int = 3) -> set[str]:
    normalized = " ".join(_tokens(value))
    if len(normalized) < size:
        return {normalized} if normalized else set()
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


def _bounded_score(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _recency_score(value: Any, now: datetime) -> float:
    updated_at = _aware_datetime(value)
    if updated_at is None:
        return 0.0
    age_days = max(0.0, (now - updated_at).total_seconds() / 86_400)
    return 1.0 / (1.0 + age_days / 30.0)


__all__ = ["DEFAULT_REPLY_MEMORY_LIMIT", "retrieve_agent_memories_for_reply"]
