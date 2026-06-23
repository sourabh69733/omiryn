from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DataPoint:
    user_id: str
    category: str
    key: str
    value: dict[str, Any]
    label: str
    confidence: float = 0.5
    source_kind: str = "agent_chat"
    source_id: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    status: str = "active"
    visibility: str = "internal"
    used_for_matching: bool = True
    used_for_chat_context: bool = False


def normalize_data_point(raw: dict[str, Any]) -> dict[str, Any]:
    point = DataPoint(
        user_id=str(raw["user_id"]),
        category=_snake_key(str(raw["category"] or "other")) or "other",
        key=_snake_key(str(raw["key"] or raw.get("label") or "data_point")) or "data_point",
        value=_normalize_value(raw.get("value") or raw.get("value_json") or {}),
        label=str(raw["label"]).strip()[:160],
        confidence=_bounded_confidence(raw.get("confidence", 0.5)),
        source_kind=str(raw.get("source_kind") or "agent_chat"),
        source_id=raw.get("source_id"),
        evidence=_normalize_evidence(raw.get("evidence") or raw.get("evidence_json") or []),
        status=str(raw.get("status") or "active"),
        visibility=str(raw.get("visibility") or "internal"),
        used_for_matching=bool(raw.get("used_for_matching", True)),
        used_for_chat_context=bool(raw.get("used_for_chat_context", False)),
    )
    return {
        "user_id": point.user_id,
        "category": point.category,
        "key": point.key,
        "value": point.value,
        "label": point.label,
        "confidence": point.confidence,
        "source_kind": point.source_kind,
        "source_id": point.source_id,
        "evidence": point.evidence,
        "status": point.status,
        "visibility": point.visibility,
        "used_for_matching": point.used_for_matching,
        "used_for_chat_context": point.used_for_chat_context,
    }


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


def _normalize_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"detail": str(value)}


def _normalize_evidence(evidence_items: list[Any]) -> list[dict[str, Any]]:
    normalized = []
    for item in evidence_items:
        if isinstance(item, dict):
            evidence = dict(item)
        else:
            evidence = {"text": str(item)}
        text = str(evidence.get("text") or evidence.get("quote") or "").strip()
        if text:
            evidence["text"] = text[:320]
            evidence["quote"] = text[:320]
        normalized.append(evidence)
    return normalized


def _bounded_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.5
    return max(0.0, min(1.0, confidence))


def _snake_key(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


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
