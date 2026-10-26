"""Enforces structural state limits while leaving semantic interpretation to the model."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import ConversationState, ConversationThread


THREAD_ORIGINS = frozenset({"user_started", "agent_started"})
THREAD_STATUSES = frozenset({"open", "paused", "completed", "blocked_by_user"})
THREAD_DEPTHS = frozenset({"mentioned", "explored", "meaningful"})
USER_INTEREST_LEVELS = frozenset({"unknown", "low", "medium", "high"})
USER_NEEDS = frozenset({"normal_chat", "listen", "answer", "explore", "play", "space"})

THREAD_MUTABLE_FIELDS = frozenset(
    {
        "last_conversation_id",
        "title",
        "summary",
        "matching_dimension",
        "status",
        "depth",
        "user_interest",
        "salience",
        "next_angle",
        "last_message_index",
        "closure_reason",
    }
)


class ConversationStateValidationError(ValueError):
    """Raised when model- or application-proposed state violates the contract."""


def validate_thread(thread: ConversationThread) -> ConversationThread:
    _required(thread.id, "thread id", 160)
    _required(thread.user_id, "thread user_id", 160)
    _required(thread.created_in_conversation_id, "created conversation id", 160)
    _required(thread.last_conversation_id, "last conversation id", 160)
    _required(thread.title, "thread title", 160)
    _required(thread.summary, "thread summary", 1200)
    _choice(thread.origin, THREAD_ORIGINS, "thread origin")
    _choice(thread.status, THREAD_STATUSES, "thread status")
    _choice(thread.depth, THREAD_DEPTHS, "thread depth")
    _choice(thread.user_interest, USER_INTEREST_LEVELS, "user interest")
    _optional_text(thread.matching_dimension, "matching dimension", 100)
    _optional_text(thread.next_angle, "next angle", 500)
    _optional_text(thread.closure_reason, "closure reason", 300)
    _index(thread.first_message_index, "first message index")
    _index(thread.last_message_index, "last message index")
    if not 0 <= float(thread.salience) <= 1:
        raise ConversationStateValidationError("thread salience must be between 0 and 1")
    if thread.version < 1:
        raise ConversationStateValidationError("thread version must be at least 1")
    return thread


def validate_thread_changes(
    thread: ConversationThread,
    changes: dict[str, Any],
) -> ConversationThread:
    unknown = set(changes) - THREAD_MUTABLE_FIELDS
    if unknown:
        raise ConversationStateValidationError(
            f"thread fields cannot be changed: {', '.join(sorted(unknown))}"
        )
    return validate_thread(replace(thread, **changes))


def validate_state(state: ConversationState) -> ConversationState:
    _required(state.conversation_id, "state conversation id", 160)
    _required(state.user_id, "state user_id", 160)
    _index(state.state_through_message_index, "state message index", allow_unset=True)
    _optional_text(state.active_thread_id, "active thread id", 160)
    _choice(state.user_need, USER_NEEDS, "user need")
    _optional_text(state.session_goal, "session goal", 500)
    if state.version < 0:
        raise ConversationStateValidationError("state version cannot be negative")
    return state


def _required(value: str, label: str, maximum: int) -> None:
    if not str(value or "").strip():
        raise ConversationStateValidationError(f"{label} is required")
    if len(str(value)) > maximum:
        raise ConversationStateValidationError(f"{label} exceeds {maximum} characters")


def _optional_text(value: str | None, label: str, maximum: int) -> None:
    if value is not None and len(str(value)) > maximum:
        raise ConversationStateValidationError(f"{label} exceeds {maximum} characters")


def _choice(value: str, allowed: frozenset[str], label: str) -> None:
    if value not in allowed:
        raise ConversationStateValidationError(f"unsupported {label}: {value}")


def _index(value: int | None, label: str, *, allow_unset: bool = False) -> None:
    minimum = -1 if allow_unset else 0
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value < minimum
    ):
        raise ConversationStateValidationError(f"{label} must be at least {minimum}")
