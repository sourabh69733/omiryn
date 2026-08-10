"""Converts extractor and storage payloads into one canonical data-point dictionary."""

from __future__ import annotations

from typing import Any

from .models import DataPoint
from .taxonomy import canonical_fact_type, snake_key


def normalize_data_point(raw: dict[str, Any]) -> dict[str, Any]:
    point = DataPoint(
        user_id=str(raw["user_id"]),
        category=snake_key(str(raw["category"] or "other")) or "other",
        key=snake_key(str(raw["key"] or raw.get("label") or "data_point")) or "data_point",
        value=_normalize_value(raw.get("value") or raw.get("value_json") or {}),
        label=str(raw["label"]).strip()[:160],
        confidence=_bounded_confidence(raw.get("confidence", 0.5)),
        fact_type=canonical_fact_type(raw.get("fact_type"), raw.get("category")),
        confidence_state=_normalize_confidence_state(raw.get("confidence_state")),
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
        "fact_type": point.fact_type,
        "confidence_state": point.confidence_state,
        "source_kind": point.source_kind,
        "source_id": point.source_id,
        "evidence": point.evidence,
        "status": point.status,
        "visibility": point.visibility,
        "used_for_matching": point.used_for_matching,
        "used_for_chat_context": point.used_for_chat_context,
    }


def _normalize_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"detail": str(value)}


def _normalize_evidence(evidence_items: list[Any]) -> list[dict[str, Any]]:
    normalized = []
    for item in evidence_items:
        evidence = dict(item) if isinstance(item, dict) else {"text": str(item)}
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


def _normalize_confidence_state(value: Any) -> str:
    clean = str(value or "active").strip().lower()
    if clean in {"candidate", "active", "confirmed", "rejected", "contradicted"}:
        return clean
    return "active"
