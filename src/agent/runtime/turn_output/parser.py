from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


ALLOWED_DATA_POINT_TYPES = {
    "profile_fact",
    "matching_fact",
    "chat_learning",
    "temporary_context",
    "needs_confirmation",
    "do_not_store",
}


@dataclass(frozen=True)
class ParsedTurnOutput:
    reply: str
    data_points: list[dict[str, Any]] = field(default_factory=list)
    parsed: bool = False
    error: str | None = None


def parse_turn_output_v2(raw_text: str, *, user_text: str) -> ParsedTurnOutput:
    raw_text = str(raw_text or "").strip()
    if not raw_text:
        return ParsedTurnOutput(reply="", data_points=[], parsed=False, error="empty_output")

    raw_json = _extract_json_object(raw_text)
    if raw_json is None:
        return ParsedTurnOutput(
            reply=raw_text,
            data_points=[],
            parsed=False,
            error="missing_json_object",
        )

    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as error:
        return ParsedTurnOutput(
            reply=raw_text,
            data_points=[],
            parsed=False,
            error=f"invalid_json:{error.msg}",
        )
    if not isinstance(payload, dict):
        return ParsedTurnOutput(
            reply=raw_text,
            data_points=[],
            parsed=False,
            error="json_not_object",
        )

    reply = str(payload.get("reply") or "").strip() or raw_text
    data_points = _normalize_data_points(payload.get("data_points"), user_text=user_text)
    return ParsedTurnOutput(reply=reply, data_points=data_points, parsed=True)


def _extract_json_object(raw_text: str) -> str | None:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    if raw_text.startswith("{") and raw_text.endswith("}"):
        return raw_text
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start >= 0 and end > start:
        return raw_text[start : end + 1]
    return None


def _normalize_data_points(raw_points: Any, *, user_text: str) -> list[dict[str, Any]]:
    if not isinstance(raw_points, list):
        return []

    normalized = []
    for raw_point in raw_points[:8]:
        if not isinstance(raw_point, dict):
            continue
        point = _normalize_data_point(raw_point, user_text=user_text)
        if point:
            normalized.append(point)
    return normalized


def _normalize_data_point(raw_point: dict[str, Any], *, user_text: str) -> dict[str, Any] | None:
    point_type = str(raw_point.get("type") or raw_point.get("fact_type") or "").strip().lower()
    if point_type not in ALLOWED_DATA_POINT_TYPES:
        return None

    label = str(raw_point.get("label") or "").strip()
    category = _snake_key(str(raw_point.get("category") or "other")) or "other"
    evidence = str(user_text or "").strip()
    if not label or not evidence:
        return None

    return {
        "type": point_type,
        "category": category[:80],
        "key": _snake_key(str(raw_point.get("key") or label))[:120] or "data_point",
        "label": label[:160],
        "value": _normalize_value(raw_point.get("value"), label),
        "evidence": evidence[:320],
        "confidence": _bounded_confidence(raw_point.get("confidence")),
    }


def _normalize_value(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None or value == "":
        return {"detail": label}
    return {"detail": str(value)}


def _bounded_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.5
    return max(0.0, min(1.0, confidence))


def _snake_key(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")
