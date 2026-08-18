"""Parses and validates inline candidates from the private companion reply envelope."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent.memory_engine.data_points import canonical_turn_data_point_type
from agent.outputs.companion_response import structured_companion_payload


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
    conversation_update: Any = None
    parsed: bool = False
    error: str | None = None
    transport_valid: bool = False
    schema_valid: bool = False
    semantic_valid: bool = False
    schema_errors: tuple[str, ...] = ()


def parse_turn_output_v2(
    raw_text: str,
    *,
    user_text: str,
    require_conversation_update: bool = False,
) -> ParsedTurnOutput:
    raw_text = str(raw_text or "").strip()
    if not raw_text:
        return ParsedTurnOutput(reply="", data_points=[], parsed=False, error="empty_output")

    payload = structured_companion_payload(raw_text)
    if payload is None:
        return ParsedTurnOutput(
            reply=raw_text,
            data_points=[],
            parsed=False,
            error="missing_json_object",
        )

    schema_errors = _validate_turn_envelope(
        payload,
        require_conversation_update=require_conversation_update,
    )
    schema_valid = not schema_errors
    reply_value = payload.get("reply")
    reply = reply_value.strip() if isinstance(reply_value, str) else ""
    data_points = _normalize_data_points(payload.get("data_points"), user_text=user_text)
    raw_points = payload.get("data_points")
    semantic_valid = (
        schema_valid and isinstance(raw_points, list) and len(data_points) == len(raw_points)
    )
    return ParsedTurnOutput(
        reply=reply or raw_text,
        data_points=data_points if schema_valid else [],
        conversation_update=payload.get("conversation_update"),
        parsed=schema_valid,
        error=None if schema_valid else "schema_invalid",
        transport_valid=True,
        schema_valid=schema_valid,
        semantic_valid=semantic_valid,
        schema_errors=tuple(schema_errors),
    )


def _validate_turn_envelope(
    payload: dict[str, Any],
    *,
    require_conversation_update: bool,
) -> list[str]:
    errors: list[str] = []
    allowed = {"reply", "data_points", "conversation_update"}
    unknown = set(payload) - allowed
    if unknown:
        errors.append(f"unsupported envelope fields: {', '.join(sorted(unknown))}")
    if not isinstance(payload.get("reply"), str) or not payload["reply"].strip():
        errors.append("reply is required and must be a non-empty string")
    raw_points = payload.get("data_points")
    if not isinstance(raw_points, list):
        errors.append("data_points is required and must be an array")
    else:
        if len(raw_points) > 8:
            errors.append("data_points cannot contain more than 8 items")
        for index, point in enumerate(raw_points[:8]):
            error = _data_point_shape_error(point)
            if error:
                errors.append(f"data_points[{index}]: {error}")
    update = payload.get("conversation_update")
    if require_conversation_update and update is None:
        errors.append("conversation_update is required")
    if update is not None:
        errors.extend(_conversation_update_shape_errors(update))
    return errors


def _data_point_shape_error(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "data point must be an object"
    required = {"type", "category", "label", "value", "confidence"}
    unknown = set(value) - required
    missing = required - set(value)
    if unknown:
        return f"unsupported fields: {', '.join(sorted(unknown))}"
    if missing:
        return f"missing fields: {', '.join(sorted(missing))}"
    if value.get("type") not in ALLOWED_DATA_POINT_TYPES:
        return "unsupported data point type"
    if not isinstance(value.get("category"), str) or not value["category"].strip():
        return "category must be a non-empty string"
    if not isinstance(value.get("label"), str) or not value["label"].strip():
        return "label must be a non-empty string"
    confidence = value.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return "confidence must be a number"
    if not 0 <= float(confidence) <= 1:
        return "confidence must be between 0 and 1"
    if value.get("value") is None or isinstance(value.get("value"), bool):
        return "value must contain a usable scalar, array, or object"
    return None


def _conversation_update_shape_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["conversation_update must be an object"]
    errors: list[str] = []
    allowed = {"user_need", "session_goal", "thread_updates"}
    unknown = set(value) - allowed
    if unknown:
        errors.append(f"unsupported conversation_update fields: {', '.join(sorted(unknown))}")
    if value.get("user_need") not in {
        "normal_chat",
        "listen",
        "answer",
        "explore",
        "play",
        "space",
    }:
        errors.append("conversation_update.user_need is invalid")
    session_goal = value.get("session_goal")
    if session_goal is not None and not isinstance(session_goal, str):
        errors.append("conversation_update.session_goal must be a string or null")
    updates = value.get("thread_updates")
    if not isinstance(updates, list):
        errors.append("conversation_update.thread_updates must be an array")
        return errors
    if not 1 <= len(updates) <= 3:
        errors.append("conversation_update.thread_updates must contain 1 to 3 actions")
    operations = [item.get("operation") for item in updates if isinstance(item, dict)]
    if "none" in operations and len(updates) != 1:
        errors.append("none must be the only thread action")
    for index, update in enumerate(updates[:3]):
        error = _thread_action_shape_error(update)
        if error:
            errors.append(f"thread_updates[{index}]: {error}")
    return errors


def _thread_action_shape_error(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "thread action must be an object"
    operation = value.get("operation")
    common_updates = {
        "title",
        "summary",
        "matching_dimension",
        "depth",
        "user_interest",
        "salience",
        "next_angle",
    }
    allowed_by_operation = {
        "none": {"operation"},
        "create": {"operation", "origin", *common_updates},
        "continue": {"operation", "thread_id", *common_updates},
        "switch": {"operation", "thread_id", *common_updates},
        "pause": {"operation", "thread_id", "summary", "next_angle", "closure_reason"},
        "complete": {"operation", "thread_id", "summary", "closure_reason"},
        "block": {"operation", "thread_id", "summary", "closure_reason"},
    }
    allowed = allowed_by_operation.get(operation)
    if allowed is None:
        return f"unsupported operation: {operation}"
    unknown = set(value) - allowed
    if unknown:
        return f"unsupported fields for {operation}: {', '.join(sorted(unknown))}"
    required = {"operation"}
    if operation == "create":
        required.update({"title", "summary", "origin"})
    elif operation != "none":
        required.add("thread_id")
    missing = required - set(value)
    if missing:
        return f"missing fields for {operation}: {', '.join(sorted(missing))}"
    if operation == "create" and value.get("origin") not in {"user_started", "agent_started"}:
        return "create origin must be user_started or agent_started"
    if operation != "create" and operation != "none":
        if not isinstance(value.get("thread_id"), str) or not value["thread_id"].strip():
            return f"{operation} requires a non-empty thread_id"
    for field_name in allowed - {"operation", "salience"}:
        if (
            field_name in value
            and value[field_name] is not None
            and not isinstance(value[field_name], str)
        ):
            return f"{field_name} must be a string or null"
    salience = value.get("salience")
    if salience is not None and (
        isinstance(salience, bool)
        or not isinstance(salience, (int, float))
        or not 0 <= float(salience) <= 1
    ):
        return "salience must be a number between 0 and 1"
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
    point_type = canonical_turn_data_point_type(point_type, category)
    evidence = str(user_text or "").strip()
    value = _normalize_value(raw_point.get("value"), user_text=user_text)
    if not label or not evidence or not value:
        return None

    return {
        "type": point_type,
        "category": category[:80],
        "key": _snake_key(str(raw_point.get("key") or label))[:120] or "data_point",
        "label": label[:160],
        "value": value,
        "evidence": evidence[:320],
        "confidence": _bounded_confidence(raw_point.get("confidence")),
    }


def _normalize_value(value: Any, *, user_text: str) -> dict[str, Any] | None:
    grounded = _ground_value(value, user_text=user_text)
    if grounded is None:
        return None
    if isinstance(grounded, dict):
        return grounded
    return {"detail": grounded}


def _ground_value(value: Any, *, user_text: str) -> Any | None:
    if isinstance(value, dict):
        grounded = {
            str(key): grounded_value
            for key, item in value.items()
            if (grounded_value := _ground_value(item, user_text=user_text)) is not None
        }
        return grounded or None
    if isinstance(value, list):
        grounded_items = [
            grounded
            for item in value
            if (grounded := _ground_value(item, user_text=user_text)) is not None
        ]
        return _dedupe_grounded_values(grounded_items) or None
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized_value = _grounding_text(text)
    normalized_user = _grounding_text(user_text)
    if not normalized_value or f" {normalized_value} " not in f" {normalized_user} ":
        return None
    return value


def _dedupe_grounded_values(values: list[Any]) -> list[Any]:
    deduped: list[Any] = []
    seen: set[str] = set()
    for value in values:
        identity = _grounding_text(str(value))
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(value)
    return deduped


def _grounding_text(value: str) -> str:
    return " ".join(
        "".join(character.casefold() if character.isalnum() else " " for character in value).split()
    )


def _bounded_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.5
    return max(0.0, min(1.0, confidence))


def _snake_key(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")
