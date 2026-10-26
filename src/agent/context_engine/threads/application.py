"""Applies validated background thread proposals exactly once."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from storage.thread_applications import apply_thread_operation_once

from .models import ConversationThread
from .validation import validate_thread


@dataclass(frozen=True)
class ThreadApplicationResult:
    """Outcome of applying zero or one normalized thread operation."""

    applied_count: int
    idempotent: bool
    thread_id: str | None
    operation: str


def apply_validated_thread_proposal(
    *,
    batch_key: str,
    conversation_id: str,
    user_id: str,
    message_index: int,
    proposal: dict[str, Any] | None,
) -> ThreadApplicationResult:
    """Persist one normalized proposal; raw provider output is not accepted."""
    if not isinstance(proposal, dict):
        raise ValueError("validated thread proposal must be an object")
    updates = proposal.get("thread_updates")
    if not isinstance(updates, list) or len(updates) > 1:
        raise ValueError("validated thread proposal must contain at most one update")
    if not updates:
        return ThreadApplicationResult(0, False, None, "none")
    normalized = updates[0]
    if not isinstance(normalized, dict):
        raise ValueError("validated thread update must be an object")
    operation_kind = str(normalized.get("operation") or "")
    if operation_kind == "create":
        operation = _create_operation(
            normalized,
            conversation_id=conversation_id,
            user_id=user_id,
            message_index=message_index,
        )
    elif operation_kind in {"continue", "switch", "pause", "complete", "block"}:
        operation = {
            "operation": operation_kind,
            "thread_id": normalized.get("thread_id"),
            "changes": normalized.get("changes"),
        }
    else:
        raise ValueError(f"unsupported validated thread operation: {operation_kind or 'missing'}")

    stored = apply_thread_operation_once(
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "batch_key": batch_key,
            "operation_fingerprint": _fingerprint(normalized),
            "operation": operation,
        }
    )
    return ThreadApplicationResult(
        applied_count=1,
        idempotent=bool(stored["idempotent"]),
        thread_id=str(stored["thread_id"]),
        operation=operation_kind,
    )


def _create_operation(
    normalized: dict[str, Any],
    *,
    conversation_id: str,
    user_id: str,
    message_index: int,
) -> dict[str, Any]:
    fields = normalized.get("thread")
    if not isinstance(fields, dict):
        raise ValueError("validated create operation requires thread fields")
    thread = validate_thread(
        ConversationThread(
            id=str(uuid4()),
            user_id=user_id,
            created_in_conversation_id=conversation_id,
            last_conversation_id=conversation_id,
            title=str(fields.get("title") or ""),
            summary=str(fields.get("summary") or ""),
            origin=str(fields.get("origin") or ""),
            matching_dimension=fields.get("matching_dimension"),
            depth=str(fields.get("depth") or "mentioned"),
            user_interest=str(fields.get("user_interest") or "unknown"),
            salience=float(fields.get("salience", 0.5)),
            next_angle=fields.get("next_angle"),
            first_message_index=message_index,
            last_message_index=message_index,
        )
    )
    return {"operation": "create", "thread": asdict(thread)}


def _fingerprint(operation: dict[str, Any]) -> str:
    encoded = json.dumps(
        operation,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["ThreadApplicationResult", "apply_validated_thread_proposal"]
