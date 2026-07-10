from __future__ import annotations

from agent.context_engine.models import ContextQueryIntent, ConversationPlan, EmotionState, TopicState
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
    emotion_state: EmotionState | None = None,
) -> ConversationPlan:
    labels = set(intent.labels)
    active = active_topic_state(topic_states)
    avoid_topics = _avoid_topics(labels, topic_states)
    suggested_topics = tuple(
        topic.label for topic in relevant_topics_for_intent(user_text, intent, limit=3)
    )
    data_targets = _data_targets(user_text, intent)
    emotion = emotion_state or EmotionState()
    response_mode = _response_mode(user_text, labels, emotion)
    move = _conversation_move(labels, active, emotion)
    return ConversationPlan(
        current_move=move,
        response_mode=response_mode,
        active_topic=active.label if active else None,
        avoid_topics=avoid_topics,
        suggested_topics=suggested_topics,
        data_targets=data_targets,
        tone_instruction=_tone_instruction(labels, emotion),
        reason=_plan_reason(labels, active, emotion),
    )


def _conversation_move(
    labels: set[str],
    active: TopicState | None,
    emotion: EmotionState,
) -> str:
    if "whatsapp" in labels and "style" in labels:
        return "specific_context_observation"
    if "whatsapp" in labels:
        return "direct_answer_from_context"
    if "adult_flirty" in labels:
        return "safe_flirty_tease"
    if "simple_ack" in labels:
        return "simple_acknowledgement"
    if emotion.response_mode in {"empathize_listen", "validate_then_suggest"}:
        return "empathize_first"
    if emotion.response_mode == "apologize_and_adjust":
        return "acknowledge_then_recover"
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


def _response_mode(user_text: str, labels: set[str], emotion: EmotionState) -> str:
    if emotion.response_mode and emotion.response_mode != "normal_chat":
        return emotion.response_mode
    if "simple_ack" in labels:
        return "simple_ack"
    normalized = user_text.casefold()
    if "what should i do" in normalized or "suggest" in normalized or "advice" in normalized:
        return "suggest_solution"
    return "normal_chat"


def _tone_instruction(labels: set[str], emotion: EmotionState) -> str:
    if "simple_ack" in labels:
        return "Reply with a tiny acknowledgement only, like 'welcome', 'sure', 'okay', or 'no worries'. Do not add advice, a new topic, or a question."
    if emotion.response_mode == "apologize_and_adjust":
        return "Briefly acknowledge the user is not enjoying this, do not defend yourself, then change approach."
    if emotion.response_mode == "empathize_listen":
        return "Listen first. Validate the feeling briefly. Do not give advice unless the user asks."
    if emotion.response_mode == "validate_then_suggest":
        return "Validate first, then offer one small practical suggestion."
    if emotion.response_mode == "clarify":
        return "Clarify gently without making the user feel wrong."
    if "adult_flirty" in labels:
        return "Keep it playful/flirty but non-graphic, consensual, and easy to back away from."
    if "boredom_complaint" in labels:
        return "Recover from boredom with a sharper dating/personal angle. Do not start music, movies, truth-or-dare, or day-check smalltalk."
    if "low_information" in labels:
        return "Bring energy with one fresh playful angle; do not sound like an interview or use generic common topics."
    if "whatsapp" in labels:
        return "Be concrete. Use stored WhatsApp context if available and admit uncertainty only when needed."
    return "React first, use known context, and ask at most one natural question."


def _plan_reason(labels: set[str], active: TopicState | None, emotion: EmotionState) -> str:
    if emotion.emotion != "neutral" and emotion.confidence >= 0.5:
        return f"Emotion={emotion.emotion}; need={emotion.need}; strategy={emotion.strategy}."
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
