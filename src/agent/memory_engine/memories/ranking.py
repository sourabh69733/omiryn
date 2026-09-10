"""Shared provider-neutral lexical ranking helpers for canonical memories."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any


def searchable_memory_text(memory: dict[str, Any]) -> str:
    return " ".join(
        (
            str(memory.get("key") or ""),
            json.dumps(memory.get("value"), ensure_ascii=False, sort_keys=True),
            " ".join(str(value) for value in memory.get("purposes") or []),
        )
    )


def text_relevance(query: str, candidate: str) -> float:
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


def embedding_similarity(
    query: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> float | None:
    """Return cosine similarity only for the same provider/model vector space."""
    if not query or not candidate:
        return None
    if (
        query.get("provider") != candidate.get("provider")
        or query.get("model") != candidate.get("model")
        or query.get("dimensions") != candidate.get("dimensions")
    ):
        return None
    left = query.get("values")
    right = candidate.get("values")
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
        return None
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if not left_norm or not right_norm:
        return None
    similarity = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    return max(0.0, min(1.0, similarity / (left_norm * right_norm)))


def bounded_score(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def recency_score(value: Any, now: datetime) -> float:
    updated_at = aware_datetime(value)
    if updated_at is None:
        return 0.0
    age_days = max(0.0, (now - updated_at).total_seconds() / 86_400)
    return 1.0 / (1.0 + age_days / 30.0)


def aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[\w']+", value.casefold()) if len(token) >= 2]


def _character_ngrams(value: str, size: int = 3) -> set[str]:
    normalized = " ".join(_tokens(value))
    if len(normalized) < size:
        return {normalized} if normalized else set()
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


__all__ = [
    "aware_datetime",
    "bounded_score",
    "embedding_similarity",
    "recency_score",
    "searchable_memory_text",
    "text_relevance",
]
