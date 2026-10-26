"""Selects a small read-only set of persistent threads for model continuity context."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from agent.config import agent_pipeline_config
from agent.context_engine.contracts.models import ThreadGuidance, ThreadReference
from text_vectors import build_text_embedding, cosine_similarity

from .models import ConversationThread
from .service import get_state, get_thread, list_threads


CONVERSATION_THREAD_SOURCE_TYPE = "conversation_threads"
CONVERSATION_THREAD_CONTEXT_LIMIT = 3
CROSS_SESSION_RELEVANCE_MINIMUM = 0.12
BACKGROUND_THREAD_CANDIDATE_LIMIT = 4
# A topic from another chat is brought back only if the user raised it and it is still fresh.
CROSS_SESSION_THREAD_MAX_AGE = timedelta(days=14)


def conversation_state_v2_enabled() -> bool:
    return agent_pipeline_config().conversation_state_enabled


def conversation_state_shadow_enabled() -> bool:
    return agent_pipeline_config().conversation_state_shadow


def conversation_thread_guidance(
    conversation_id: str,
    user_id: str | None,
    user_text: str = "",
) -> ThreadGuidance:
    """Select bounded persistent threads for one foreground planning decision."""
    if not user_id or not conversation_state_v2_enabled():
        return ThreadGuidance()

    state = get_state(conversation_id, user_id)
    active = (
        get_thread(state.active_thread_id, user_id)
        if state and state.active_thread_id
        else None
    )
    if active and active.status != "open":
        active = None
    ranked = _rank_open_thread_candidates(
        list_threads(user_id, statuses=("open",)),
        conversation_id=conversation_id,
        user_text=user_text,
        active_thread_id=active.id if active else None,
    )
    return ThreadGuidance(
        active=_thread_reference(active, conversation_id) if active else None,
        relevant_open=tuple(
            _thread_reference(thread, conversation_id)
            for thread in ranked[:CONVERSATION_THREAD_CONTEXT_LIMIT - bool(active)]
        ),
    )


def conversation_thread_context_sources(
    conversation_id: str,
    user_id: str | None,
    user_text: str = "",
    *,
    guidance: ThreadGuidance | None = None,
) -> list[dict[str, Any]]:
    selected_guidance = guidance or conversation_thread_guidance(
        conversation_id,
        user_id,
        user_text,
    )
    selected = tuple(
        reference
        for reference in (selected_guidance.active, *selected_guidance.relevant_open)
        if reference is not None
    )
    if not selected:
        return []

    lines = [
        "Private conversation continuity notes.",
        "The current user message has priority. Use a note only when it connects naturally; do not expose internal thread names, statuses, or tracking.",
    ]
    for thread in selected:
        role = (
            "current"
            if selected_guidance.active and thread.id == selected_guidance.active.id
            else "open"
        )
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
                "active_thread_id": (
                    selected_guidance.active.id if selected_guidance.active else None
                ),
                "thread_ids": [thread.id for thread in selected],
                "cross_session_thread_ids": [
                    thread.id for thread in selected if thread.cross_session
                ],
                "thread_count": len(selected),
                "read_only": True,
            },
        }
    ]


def _thread_reference(
    thread: ConversationThread,
    conversation_id: str,
) -> ThreadReference:
    return ThreadReference(
        id=thread.id,
        title=thread.title,
        summary=thread.summary,
        origin=thread.origin,
        user_interest=thread.user_interest,
        next_angle=thread.next_angle,
        cross_session=thread.last_conversation_id != conversation_id,
    )


def background_thread_candidates(
    conversation_id: str,
    user_id: str,
    query_text: str,
    *,
    limit: int = BACKGROUND_THREAD_CANDIDATE_LIMIT,
) -> list[dict[str, object]]:
    """Return bounded, owned thread records for background model classification."""
    if not user_id or limit <= 0:
        return []
    state = get_state(conversation_id, user_id)
    active = (
        get_thread(state.active_thread_id, user_id)
        if state and state.active_thread_id
        else None
    )
    threads = list_threads(
        user_id,
        statuses=("open", "paused", "completed", "blocked_by_user"),
    )
    ranked = _rank_thread_candidates(
        threads,
        conversation_id=conversation_id,
        user_text=query_text,
        excluded_thread_id=active.id if active else None,
    )
    selected = (([active] if active else []) + ranked)[:limit]
    return [
        {
            "id": thread.id,
            "user_id": thread.user_id,
            "title": thread.title,
            "summary": thread.summary,
            "status": thread.status,
            "origin": thread.origin,
            "active": bool(active and active.id == thread.id),
            "version": thread.version,
            "matching_dimension": thread.matching_dimension,
            "depth": thread.depth,
            "user_interest": thread.user_interest,
            "salience": thread.salience,
            "next_angle": thread.next_angle,
            "last_conversation_id": thread.last_conversation_id,
        }
        for thread in selected
    ]


def _rank_open_thread_candidates(
    threads: list[ConversationThread],
    *,
    conversation_id: str,
    user_text: str,
    active_thread_id: str | None,
) -> list[ConversationThread]:
    """Rank current threads plus relevant prior-session threads without changing state."""
    return _rank_thread_candidates(
        threads,
        conversation_id=conversation_id,
        user_text=user_text,
        excluded_thread_id=active_thread_id,
    )


def _rank_thread_candidates(
    threads: list[ConversationThread],
    *,
    conversation_id: str,
    user_text: str,
    excluded_thread_id: str | None,
) -> list[ConversationThread]:
    query_embedding = build_text_embedding(user_text) if user_text.strip() else None
    candidates: list[tuple[float, int, ConversationThread]] = []
    for recency_index, thread in enumerate(threads):
        if thread.id == excluded_thread_id:
            continue
        current_conversation = thread.last_conversation_id == conversation_id
        if not current_conversation and not _carries_across_chats(thread):
            continue
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


def _carries_across_chats(thread: ConversationThread, now: datetime | None = None) -> bool:
    if thread.origin != "user_started" or not thread.updated_at:
        return False
    try:
        updated = datetime.fromisoformat(thread.updated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - updated <= CROSS_SESSION_THREAD_MAX_AGE
