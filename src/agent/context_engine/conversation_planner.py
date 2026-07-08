from __future__ import annotations

from agent.context_engine.models import ContextQueryIntent, ConversationPlan, TopicState
from agent.context_engine.topic_catalog import COMMON_STARTER_TOPIC_POLICY, relevant_topics_for_intent
from agent.context_engine.topic_state import active_topic_state, avoid_topic_labels

COMMON_STARTER_AVOID_TOPICS = (
    "Generic music preference starters.",
    "Generic movie preference starters.",
    "Truth-or-dare game starters.",
    "Repeated how-was-your-day/opening-smalltalk questions.",
)


def build_conversation_plan(
    *,
    user_text: str,
    intent: ContextQueryIntent,
    topic_states: list[TopicState],
) -> ConversationPlan:
    labels = set(intent.labels)
    active = active_topic_state(topic_states)
    avoid_topics = _avoid_topics(labels, topic_states)
    suggested_topics = tuple(
        topic.label for topic in relevant_topics_for_intent(user_text, intent, limit=3)
    )
    data_targets = _data_targets(user_text, intent)
    move = _conversation_move(labels, active)
    return ConversationPlan(
        current_move=move,
        active_topic=active.label if active else None,
        avoid_topics=avoid_topics,
        suggested_topics=suggested_topics,
        data_targets=data_targets,
        tone_instruction=_tone_instruction(labels),
        reason=_plan_reason(labels, active),
    )


def _conversation_move(labels: set[str], active: TopicState | None) -> str:
    if "whatsapp" in labels and "style" in labels:
        return "specific_context_observation"
    if "whatsapp" in labels:
        return "direct_answer_from_context"
    if "adult_flirty" in labels:
        return "safe_flirty_tease"
    if "story_or_long_reply" in labels:
        return "mini_story"
    if {"low_information", "boredom_complaint"} & labels:
        return "boredom_rescue"
    if active and active.status == "avoid_repeating":
        return "topic_bridge"
    if active and active.bucket in {"romantic", "intimate_safe"}:
        return "playful_guess"
    return "specific_observation"


def _data_targets(user_text: str, intent: ContextQueryIntent) -> tuple[str, ...]:
    targets: list[str] = []
    for topic in relevant_topics_for_intent(user_text, intent, limit=3):
        for target in topic.data_targets:
            if target not in targets:
                targets.append(target)
    return tuple(targets[:5])


def _tone_instruction(labels: set[str]) -> str:
    if "adult_flirty" in labels:
        return "Keep it playful/flirty but non-graphic, consensual, and easy to back away from."
    if "boredom_complaint" in labels:
        return "Recover from boredom with a sharper dating/personal angle. Do not start music, movies, truth-or-dare, or day-check smalltalk."
    if "low_information" in labels:
        return "Bring energy with one fresh playful angle; do not sound like an interview or use generic common topics."
    if "whatsapp" in labels:
        return "Be concrete. Use stored WhatsApp context if available and admit uncertainty only when needed."
    return "React first, use known context, and ask at most one natural question."


def _plan_reason(labels: set[str], active: TopicState | None) -> str:
    if labels:
        return f"Intent labels: {', '.join(sorted(labels))}."
    if active:
        return f"Continue from active topic bucket: {active.bucket}."
    return "Default companion flow."


def _avoid_topics(labels: set[str], topic_states: list[TopicState]) -> tuple[str, ...]:
    avoided = list(avoid_topic_labels(topic_states))
    for topic in COMMON_STARTER_AVOID_TOPICS:
        if topic not in avoided:
            avoided.append(topic)
    if "common_topic" in labels or "boredom_complaint" in labels:
        for policy in COMMON_STARTER_TOPIC_POLICY:
            if policy not in avoided:
                avoided.append(policy)
    return tuple(avoided)
