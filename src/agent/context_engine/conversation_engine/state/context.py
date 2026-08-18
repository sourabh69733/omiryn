"""Selects a small read-only set of persistent threads for model continuity context."""

from __future__ import annotations

import os
from typing import Any

from text_vectors import build_text_embedding, cosine_similarity

from .models import ConversationThread
from .service import get_state, get_thread, list_threads


CONVERSATION_THREAD_SOURCE_TYPE = "conversation_threads"
CONVERSATION_THREAD_CONTEXT_LIMIT = 3
CROSS_SESSION_RELEVANCE_MINIMUM = 0.12


def conversation_state_v2_enabled() -> bool:
    return os.getenv("CONVERSATION_STATE_V2_ENABLED", "true").strip().lower() == "true"


def conversation_state_shadow_enabled() -> bool:
    return conversation_state_v2_enabled() and (
        os.getenv("CONVERSATION_STATE_V2_SHADOW_ENABLED", "false").strip().lower()
        == "true"
    )


def conversation_thread_context_sources(
    conversation_id: str,
    user_id: str | None,
    user_text: str = "",
) -> list[dict[str, Any]]:
    if not user_id or not conversation_state_v2_enabled():
        return []

    state = get_state(conversation_id, user_id)
    active = (
        get_thread(state.active_thread_id, user_id)
        if state and state.active_thread_id
        else None
    )
    if active and active.status != "open":
        active = None

    all_open = list_threads(user_id, statuses=("open",))
    ranked = _rank_open_thread_candidates(
        all_open,
        conversation_id=conversation_id,
        user_text=user_text,
        active_thread_id=active.id if active else None,
    )
    selected = ([active] if active else []) + ranked
    selected = selected[:CONVERSATION_THREAD_CONTEXT_LIMIT]
    if not selected:
        return []

    lines = [
        "Private conversation continuity notes.",
        "The current user message has priority. Use a note only when it connects naturally; do not expose internal thread names, statuses, or tracking.",
    ]
    for thread in selected:
        role = "current" if active and thread.id == active.id else "open"
        lines.append(f"- {role}; thread_id={thread.id}: {thread.title}")
        lines.append(f"  Summary: {thread.summary}")
        if thread.next_angle:
            lines.append(f"  Possible continuation: {thread.next_angle}")

    return [
        {
            "source_type": CONVERSATION_THREAD_SOURCE_TYPE,
            "title": "Conversation continuity",
            "content": "\n".join(lines),
            "metadata": {
                "active_thread_id": active.id if active else None,
                "thread_ids": [thread.id for thread in selected],
                "cross_session_thread_ids": [
                    thread.id
                    for thread in selected
                    if thread.last_conversation_id != conversation_id
                ],
                "thread_count": len(selected),
                "read_only": True,
            },
        }
    ]


def _rank_open_thread_candidates(
    threads: list[ConversationThread],
    *,
    conversation_id: str,
    user_text: str,
    active_thread_id: str | None,
) -> list[ConversationThread]:
    """Rank current threads plus relevant prior-session threads without changing state."""
    query_embedding = build_text_embedding(user_text) if user_text.strip() else None
    candidates: list[tuple[float, int, ConversationThread]] = []
    for recency_index, thread in enumerate(threads):
        if thread.id == active_thread_id:
            continue
        current_conversation = thread.last_conversation_id == conversation_id
        thread_text = " ".join(
            value
            for value in (thread.title, thread.summary, thread.next_angle)
            if value
        )
        relevance = cosine_similarity(query_embedding, build_text_embedding(thread_text))
        if not current_conversation and relevance < CROSS_SESSION_RELEVANCE_MINIMUM:
            continue
        score = (
            relevance * 0.8
            + float(thread.salience) * 0.1
            + (0.1 if current_conversation else 0.0)
        )
        candidates.append((score, -recency_index, thread))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [thread for _, _, thread in candidates]
