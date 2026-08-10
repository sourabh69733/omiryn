from __future__ import annotations

from typing import Any

from agent.context_engine.models import ContextQueryIntent, TopicState
from agent.context_engine.topic_catalog import TopicDefinition, relevant_topics_for_intent
from agent.context_engine.utils import normalized_memory_text


RECENT_TOPIC_SCAN_LIMIT = 16


def build_topic_state(
    messages: list[dict[str, Any]],
    user_text: str,
    intent: ContextQueryIntent,
) -> list[TopicState]:
    recent_messages = messages[-RECENT_TOPIC_SCAN_LIMIT:]
    candidates = relevant_topics_for_intent(user_text, intent, limit=5)
    states: list[TopicState] = []
    for topic in candidates:
        repeat_count, last_seen = _topic_mentions(topic, recent_messages, user_text)
        status = _topic_status(topic, repeat_count, last_seen)
        states.append(
            TopicState(
                topic_id=topic.id,
                label=topic.label,
                bucket=topic.bucket,
                status=status,
                depth=_topic_depth(repeat_count),
                last_seen_turns_ago=last_seen,
                repeat_count=repeat_count,
                user_interest=_user_interest(repeat_count, last_seen),
            )
        )
    return states


def active_topic_state(topic_states: list[TopicState]) -> TopicState | None:
    for state in topic_states:
        if state.status in {"new", "active"}:
            return state
    return topic_states[0] if topic_states else None


def avoid_topic_labels(topic_states: list[TopicState]) -> tuple[str, ...]:
    return tuple(
        state.label
        for state in topic_states
        if state.status in {"avoid_repeating", "exhausted"}
    )


def _topic_mentions(
    topic: TopicDefinition,
    messages: list[dict[str, Any]],
    current_user_text: str,
) -> tuple[int, int | None]:
    search_texts = [str(message.get("content") or "") for message in messages]
    search_texts.append(current_user_text)
    repeat_count = 0
    last_seen: int | None = None
    for reverse_index, text in enumerate(reversed(search_texts)):
        normalized = normalized_memory_text(text)
        if any(term in normalized for term in topic.trigger_terms):
            repeat_count += 1
            if last_seen is None:
                last_seen = reverse_index
    return repeat_count, last_seen


def _topic_status(topic: TopicDefinition, repeat_count: int, last_seen: int | None) -> str:
    if repeat_count == 0:
        return "new"
    if repeat_count >= 4 and last_seen is not None and last_seen <= topic.freshness_window:
        return "avoid_repeating"
    if repeat_count >= 6:
        return "exhausted"
    if last_seen is not None and last_seen <= topic.freshness_window:
        return "active"
    return "stale"


def _topic_depth(repeat_count: int) -> str:
    if repeat_count >= 5:
        return "deep"
    if repeat_count >= 2:
        return "medium"
    return "shallow"


def _user_interest(repeat_count: int, last_seen: int | None) -> str:
    if repeat_count >= 3 and last_seen is not None and last_seen <= 8:
        return "high"
    if repeat_count >= 1:
        return "medium"
    return "unknown"
