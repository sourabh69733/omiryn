"""Ranks approved chat-context data points against the user's current message."""

from __future__ import annotations

import re
from typing import Any


def rank_data_points_for_context(
    data_points: list[dict[str, Any]],
    user_text: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    query_terms = _terms(user_text)
    candidates = [
        point
        for point in data_points
        if point.get("status") == "active" and point.get("used_for_chat_context")
    ]
    scored = [(_context_score(point, query_terms), point) for point in candidates]
    scored = [(score, point) for score, point in scored if score > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [point for _, point in scored[:limit]]


def _context_score(point: dict[str, Any], query_terms: set[str]) -> float:
    text = " ".join(
        [
            str(point.get("category") or ""),
            str(point.get("key") or ""),
            str(point.get("label") or ""),
            _value_text(point.get("value")),
        ]
    ).lower()
    score = float(point.get("confidence") or 0)
    if query_terms:
        score += sum(text.count(term) for term in query_terms)
    return score


def _terms(text: str) -> set[str]:
    stop_words = {"the", "and", "for", "you", "your", "about", "with", "from", "what", "this"}
    return {
        token
        for token in re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
        if len(token) >= 3 and token not in stop_words
    }


def _value_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(part) for part in value.values())
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return str(value or "")
