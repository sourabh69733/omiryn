"""Selects a small read-only set of persistent threads for model continuity context."""

from __future__ import annotations

import os
from typing import Any

from .service import get_state, get_thread, list_threads


CONVERSATION_THREAD_SOURCE_TYPE = "conversation_threads"
CONVERSATION_THREAD_CONTEXT_LIMIT = 3


def conversation_state_v2_enabled() -> bool:
    return os.getenv("CONVERSATION_STATE_V2_ENABLED", "true").strip().lower() == "true"


def conversation_thread_context_sources(
    conversation_id: str,
    user_id: str | None,
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

    current_open = list_threads(
        user_id,
        statuses=("open",),
        conversation_id=conversation_id,
    )
    selected = ([active] if active else []) + [
        thread for thread in current_open if not active or thread.id != active.id
    ]
    selected = selected[:CONVERSATION_THREAD_CONTEXT_LIMIT]
    if not selected:
        return []

    lines = [
        "Private conversation continuity notes.",
        "The current user message has priority. Use a note only when it connects naturally; do not expose internal thread names, statuses, or tracking.",
    ]
    for thread in selected:
        role = "current" if active and thread.id == active.id else "open"
        lines.append(f"- {role}: {thread.title}")
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
                "thread_count": len(selected),
                "read_only": True,
            },
        }
    ]
