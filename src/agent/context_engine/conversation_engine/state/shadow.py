"""Validates model-proposed thread changes for observation without persisting them."""

from __future__ import annotations

from typing import Any

from .models import ConversationState, ConversationThread
from .service import list_threads
from .validation import (
    ConversationStateValidationError,
    validate_state,
    validate_thread,
    validate_thread_changes,
)


THREAD_OPERATIONS = frozenset(
    {"none", "create", "continue", "switch", "pause", "complete", "block"}
)
MAX_THREAD_UPDATES_PER_TURN = 3
_TOP_LEVEL_FIELDS = frozenset({"user_need", "session_goal", "thread_updates"})
_THREAD_UPDATE_FIELDS = frozenset(
    {
        "operation",
        "thread_id",
        "title",
        "summary",
        "origin",
        "matching_dimension",
        "depth",
        "user_interest",
        "salience",
        "next_angle",
        "closure_reason",
    }
)


def evaluate_conversation_update_shadow(
    raw_update: Any,
    *,
    conversation_id: str,
    user_id: str | None,
    message_index: int,
) -> dict[str, Any]:
    """Return an encrypted-trace-safe validation summary; this function never writes state."""
    if not user_id:
        return _result(False, None, ["conversation state requires a user_id"])
    if not isinstance(raw_update, dict):
        return _result(False, None, ["conversation_update must be an object"])

    errors: list[str] = []
    unknown = set(raw_update) - _TOP_LEVEL_FIELDS
    if unknown:
        errors.append(f"unsupported conversation_update fields: {', '.join(sorted(unknown))}")

    user_need = raw_update.get("user_need")
    session_goal = raw_update.get("session_goal")
    if not isinstance(user_need, str):
        errors.append("user_need is required and must be a string")
    if session_goal is not None and not isinstance(session_goal, str):
        errors.append("session_goal must be a string or null")
    if isinstance(user_need, str):
        try:
            validate_state(
                ConversationState(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    state_through_message_index=message_index,
                    user_need=user_need,
                    session_goal=session_goal if isinstance(session_goal, str) else None,
                )
            )
        except ConversationStateValidationError as error:
            errors.append(str(error))

    raw_thread_updates = raw_update.get("thread_updates")
    if not isinstance(raw_thread_updates, list):
        errors.append("thread_updates is required and must be an array")
        raw_thread_updates = []
    if len(raw_thread_updates) > MAX_THREAD_UPDATES_PER_TURN:
        errors.append(
            f"thread_updates cannot contain more than {MAX_THREAD_UPDATES_PER_TURN} items"
        )
    raw_operations = [
        item.get("operation")
        for item in raw_thread_updates
        if isinstance(item, dict)
    ]
    if "none" in raw_operations and len(raw_thread_updates) != 1:
        errors.append("none must be the only thread update")

    existing = {thread.id: thread for thread in list_threads(user_id)}
    normalized_updates: list[dict[str, Any]] = []
    seen_thread_ids: set[str] = set()
    create_count = 0
    for index, raw_thread_update in enumerate(raw_thread_updates[:MAX_THREAD_UPDATES_PER_TURN]):
        try:
            normalized = _validate_thread_update(
                raw_thread_update,
                existing=existing,
                conversation_id=conversation_id,
                user_id=user_id,
                message_index=message_index,
                shadow_index=index,
            )
            if normalized["operation"] == "none":
                continue
            if normalized["operation"] == "create":
                create_count += 1
                if create_count > 1:
                    raise ConversationStateValidationError(
                        "only one new conversation thread is allowed per turn"
                    )
            else:
                thread_id = normalized["thread_id"]
                if thread_id in seen_thread_ids:
                    raise ConversationStateValidationError(
                        "a thread can be updated only once per turn"
                    )
                seen_thread_ids.add(thread_id)
            normalized_updates.append(normalized)
        except (ConversationStateValidationError, TypeError, ValueError) as error:
            errors.append(f"thread_updates[{index}]: {error}")

    proposal = {
        "user_need": user_need if isinstance(user_need, str) else None,
        "session_goal": session_goal if isinstance(session_goal, str) else None,
        "thread_updates": normalized_updates,
    }
    return _result(True, proposal, errors)


def _validate_thread_update(
    raw: Any,
    *,
    existing: dict[str, ConversationThread],
    conversation_id: str,
    user_id: str,
    message_index: int,
    shadow_index: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConversationStateValidationError("thread update must be an object")
    unknown = set(raw) - _THREAD_UPDATE_FIELDS
    if unknown:
        raise ConversationStateValidationError(
            f"unsupported fields: {', '.join(sorted(unknown))}"
        )
    operation = raw.get("operation")
    if operation not in THREAD_OPERATIONS:
        raise ConversationStateValidationError(f"unsupported thread operation: {operation}")
    if operation == "none":
        if set(raw) != {"operation"}:
            raise ConversationStateValidationError("none operation cannot include other fields")
        return {"operation": "none"}
    if operation == "create":
        return _validate_create(
            raw,
            conversation_id=conversation_id,
            user_id=user_id,
            message_index=message_index,
            shadow_index=shadow_index,
        )

    thread_id = raw.get("thread_id")
    if not isinstance(thread_id, str) or thread_id not in existing:
        raise ConversationStateValidationError("existing operation requires an owned thread_id")
    existing_status = existing[thread_id].status
    if existing_status == "blocked_by_user" and operation != "block":
        raise ConversationStateValidationError("a user-blocked thread cannot be changed")
    if existing_status == "completed" and operation not in {"complete", "block"}:
        raise ConversationStateValidationError("a completed thread cannot be reopened")
    proposed_origin = raw.get("origin")
    if proposed_origin is not None and proposed_origin != existing[thread_id].origin:
        raise ConversationStateValidationError("an existing thread origin cannot be changed")

    for field in (
        "title",
        "summary",
        "matching_dimension",
        "depth",
        "user_interest",
        "next_angle",
        "closure_reason",
    ):
        if field in raw and raw[field] is not None and not isinstance(raw[field], str):
            raise ConversationStateValidationError(f"{field} must be a string or null")
    if "salience" in raw:
        _optional_number(raw.get("salience"), default=0.5)

    changes = {
        key: raw[key]
        for key in (
            "title",
            "summary",
            "matching_dimension",
            "depth",
            "user_interest",
            "salience",
            "next_angle",
            "closure_reason",
        )
        if key in raw and raw[key] is not None
    }
    changes.update(
        last_conversation_id=conversation_id,
        last_message_index=message_index,
    )
    status_for_operation = {
        "continue": "open",
        "switch": "open",
        "pause": "paused",
        "complete": "completed",
        "block": "blocked_by_user",
    }
    changes["status"] = status_for_operation[operation]
    validated = validate_thread_changes(existing[thread_id], changes)
    return {
        "operation": operation,
        "thread_id": thread_id,
        "changes": {
            key: getattr(validated, key)
            for key in changes
        },
    }


def _validate_create(
    raw: dict[str, Any],
    *,
    conversation_id: str,
    user_id: str,
    message_index: int,
    shadow_index: int,
) -> dict[str, Any]:
    # IDs are always generated by the runtime. Some providers may still emit a
    # schema-forbidden ID; discard it instead of ever trusting or persisting it.
    for field in ("title", "summary", "origin"):
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            raise ConversationStateValidationError(f"create operation requires {field}")
    thread = validate_thread(
        ConversationThread(
            id=f"shadow-new-{shadow_index}",
            user_id=user_id,
            created_in_conversation_id=conversation_id,
            last_conversation_id=conversation_id,
            title=raw["title"],
            summary=raw["summary"],
            origin=raw["origin"],
            matching_dimension=_optional_string(raw.get("matching_dimension")),
            depth=_optional_string(raw.get("depth")) or "mentioned",
            user_interest=_optional_string(raw.get("user_interest")) or "unknown",
            salience=_optional_number(raw.get("salience"), default=0.5),
            next_angle=_optional_string(raw.get("next_angle")),
            first_message_index=message_index,
            last_message_index=message_index,
            closure_reason=_optional_string(raw.get("closure_reason")),
        )
    )
    return {
        "operation": "create",
        "thread": {
            key: value
            for key, value in {
                "title": thread.title,
                "summary": thread.summary,
                "origin": thread.origin,
                "matching_dimension": thread.matching_dimension,
                "depth": thread.depth,
                "user_interest": thread.user_interest,
                "salience": thread.salience,
                "next_angle": thread.next_angle,
            }.items()
            if value is not None
        },
    }


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConversationStateValidationError("optional text fields must be strings or null")
    return value


def _optional_number(value: Any, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConversationStateValidationError("salience must be a number")
    return float(value)


def _result(present: bool, proposal: dict[str, Any] | None, errors: list[str]) -> dict[str, Any]:
    return {
        "present": present,
        "valid": present and not errors,
        "proposed_thread_update_count": len((proposal or {}).get("thread_updates") or []),
        "proposal": proposal,
        "errors": errors,
        "persisted": False,
    }
