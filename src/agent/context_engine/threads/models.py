"""Provides immutable domain records for resumable threads and per-session state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationThread:
    id: str
    user_id: str
    created_in_conversation_id: str
    last_conversation_id: str
    title: str
    summary: str
    origin: str
    matching_dimension: str | None = None
    status: str = "open"
    depth: str = "mentioned"
    user_interest: str = "unknown"
    salience: float = 0.5
    next_angle: str | None = None
    first_message_index: int | None = None
    last_message_index: int | None = None
    closure_reason: str | None = None
    version: int = 1
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ConversationState:
    conversation_id: str
    user_id: str
    state_through_message_index: int = -1
    active_thread_id: str | None = None
    user_need: str = "normal_chat"
    session_goal: str | None = None
    version: int = 0
    created_at: str | None = None
    updated_at: str | None = None
