"""Offers the typed persistence boundary for conversation state version 2."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4

from storage.conversation_threads import (
    ConversationStateConflictError,
    _get_conversation_state,
    _get_conversation_thread,
    _insert_conversation_thread,
    _list_conversation_threads,
    _save_conversation_state,
    _update_conversation_thread,
)

from .models import ConversationState, ConversationThread
from .validation import validate_state, validate_thread, validate_thread_changes


def create_thread(
    *,
    user_id: str,
    conversation_id: str,
    title: str,
    summary: str,
    origin: str,
    matching_dimension: str | None = None,
    status: str = "open",
    depth: str = "mentioned",
    user_interest: str = "unknown",
    salience: float = 0.5,
    next_angle: str | None = None,
    message_index: int | None = None,
) -> ConversationThread:
    thread = validate_thread(
        ConversationThread(
            id=str(uuid4()),
            user_id=user_id,
            created_in_conversation_id=conversation_id,
            last_conversation_id=conversation_id,
            title=title,
            summary=summary,
            origin=origin,
            matching_dimension=matching_dimension,
            status=status,
            depth=depth,
            user_interest=user_interest,
            salience=salience,
            next_angle=next_angle,
            first_message_index=message_index,
            last_message_index=message_index,
        )
    )
    return ConversationThread(**_insert_conversation_thread(asdict(thread)))


def get_thread(thread_id: str, user_id: str) -> ConversationThread | None:
    row = _get_conversation_thread(thread_id, user_id)
    return ConversationThread(**row) if row else None


def list_threads(
    user_id: str,
    *,
    statuses: tuple[str, ...] | None = None,
    conversation_id: str | None = None,
) -> list[ConversationThread]:
    return [
        ConversationThread(**row)
        for row in _list_conversation_threads(
            user_id,
            statuses=statuses,
            conversation_id=conversation_id,
        )
    ]


def update_thread(
    thread_id: str,
    user_id: str,
    changes: dict[str, Any],
    *,
    expected_version: int,
) -> ConversationThread:
    current = get_thread(thread_id, user_id)
    if current is None:
        raise ValueError("conversation thread was not found for this user")
    validate_thread_changes(current, changes)
    row = _update_conversation_thread(
        thread_id,
        user_id,
        changes,
        expected_version=expected_version,
    )
    return ConversationThread(**row)


def get_state(conversation_id: str, user_id: str) -> ConversationState | None:
    row = _get_conversation_state(conversation_id, user_id)
    return ConversationState(**row) if row else None


def save_state(state: ConversationState) -> ConversationState:
    validated = validate_state(state)
    row = _save_conversation_state(
        asdict(validated),
        expected_version=validated.version,
    )
    return ConversationState(**row)


__all__ = [
    "ConversationStateConflictError",
    "create_thread",
    "get_state",
    "get_thread",
    "list_threads",
    "save_state",
    "update_thread",
]
