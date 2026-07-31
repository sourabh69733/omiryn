from __future__ import annotations

from agent.context_engine.models import (
    ContextQueryIntent,
    ConversationalStance,
    ConversationPlan,
    EmotionState,
    TopicState,
)
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
    conversational_stance: ConversationalStance | None = None,
    listener_first: bool = False,
) -> ConversationPlan:
    if listener_first:
        return _build_listener_first_plan(
            user_text=user_text,
            intent=intent,
            topic_states=topic_states,
            emotion_state=emotion_state or EmotionState(),
            stance=conversational_stance or ConversationalStance(),
        )
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


def _build_listener_first_plan(
    *,
    user_text: str,
    intent: ContextQueryIntent,
    topic_states: list[TopicState],
    emotion_state: EmotionState,
    stance: ConversationalStance,
) -> ConversationPlan:
    labels = set(intent.labels)
    prioritized = _stance_requires_attention(stance)
    active = _listener_first_active_topic(topic_states, labels, prioritized)
    suggested_topics = _listener_first_suggested_topics(
        user_text,
        intent,
        topic_states,
        prioritized,
    )
    question_purpose = stance.question_purpose
    if question_purpose == "none" and not prioritized and labels & {"low_information", "boredom_complaint"}:
        question_purpose = "offer_choice"
    return ConversationPlan(
        current_move=_listener_first_move(labels, active, emotion_state, stance),
        response_mode=_listener_first_response_mode(user_text, labels, emotion_state, stance),
        active_topic=active.label if active else None,
        avoid_topics=_avoid_topics(labels, topic_states),
        suggested_topics=suggested_topics,
        data_targets=_data_targets_for_suggestions(user_text, intent, suggested_topics),
        tone_instruction=_listener_first_tone_instruction(labels, emotion_state, stance),
        reason=_listener_first_reason(labels, active, emotion_state, stance),
        stance=stance.mode,
        stance_confidence=stance.confidence,
        claim_type=stance.claim_type,
        question_purpose=question_purpose,
        user_constraints=stance.constraints,
        feedback_kind=stance.feedback_kind,
    )


def _stance_requires_attention(stance: ConversationalStance) -> bool:
    return bool(
        stance.feedback_kind
        or stance.constraints
        or stance.mode
        in {"agree", "partially_agree", "disagree", "challenge_gently", "validate_experience", "uncertain"}
    )


def _listener_first_active_topic(
    topic_states: list[TopicState],
    labels: set[str],
    prioritized: bool,
) -> TopicState | None:
    if prioritized:
        return None
    if labels & {"low_information", "boredom_complaint"}:
        return active_topic_state(topic_states)
    return next(
        (
            state
            for state in topic_states
            if state.repeat_count > 0 and state.status in {"new", "active"}
        ),
        None,
    )


def _listener_first_suggested_topics(
    user_text: str,
    intent: ContextQueryIntent,
    topic_states: list[TopicState],
    prioritized: bool,
) -> tuple[str, ...]:
    if prioritized:
        return ()
    labels = set(intent.labels)
    has_grounded_topic = any(state.repeat_count > 0 for state in topic_states)
    if not has_grounded_topic and not labels & {"low_information", "boredom_complaint"}:
        return ()
    return tuple(topic.label for topic in relevant_topics_for_intent(user_text, intent, limit=3))


def _data_targets_for_suggestions(
    user_text: str,
    intent: ContextQueryIntent,
    suggested_topics: tuple[str, ...],
) -> tuple[str, ...]:
    if not suggested_topics:
        return ()
    return _data_targets(user_text, intent)


def _listener_first_response_mode(
    user_text: str,
    labels: set[str],
    emotion: EmotionState,
    stance: ConversationalStance,
) -> str:
    constraints = set(stance.constraints)
    if "give_space" in constraints:
        return "give_space"
    if stance.feedback_kind:
        return "respond_to_feedback"
    if constraints & {"no_advice", "listen_only"}:
        return "empathize_listen"
    if stance.mode in {"disagree", "challenge_gently", "partially_agree", "agree", "uncertain"}:
        return stance.mode
    if stance.mode == "validate_experience" and emotion.response_mode == "normal_chat":
        return "empathize_listen"
    return _response_mode(user_text, labels, emotion)


def _listener_first_move(
    labels: set[str],
    active: TopicState | None,
    emotion: EmotionState,
    stance: ConversationalStance,
) -> str:
    if "give_space" in stance.constraints:
        return "respect_space"
    if stance.feedback_kind:
        return "repair_with_backbone"
    moves = {
        "agree": "agree_with_reason",
        "partially_agree": "partial_agreement",
        "disagree": "disagree_gently",
        "challenge_gently": "challenge_assumption",
        "validate_experience": "validate_experience",
        "uncertain": "clarify_claim",
    }
    if stance.mode in moves:
        return moves[stance.mode]
    return _conversation_move(labels, active, emotion)


def _listener_first_tone_instruction(
    labels: set[str],
    emotion: EmotionState,
    stance: ConversationalStance,
) -> str:
    constraints = set(stance.constraints)
    if "give_space" in constraints:
        return "Respect the request for space with one brief acknowledgment. Do not ask a question or restart the conversation."
    if stance.feedback_kind:
        stance_rules = {
            "agree": "Own the accurate feedback briefly and adjust.",
            "partially_agree": "Accept the valid experience while gently qualifying any overstatement.",
            "disagree": "Correct the inaccurate frequency claim using recent evidence, while taking the user's unwanted experience seriously.",
            "uncertain": "Do not assume the claim is true; acknowledge the experience and clarify what created that impression.",
        }
        return (
            f"{stance_rules.get(stance.mode, 'Respond to the feedback directly.')} "
            "Do not become defensive, automatically apologize, or promise passive obedience."
        )
    if "no_questions" in constraints:
        return "Do not ask a question. Respond directly and stay with the user's active point."
    if constraints & {"no_advice", "listen_only"}:
        return "Listen and reflect the specific experience. Do not give advice, solutions, or a disguised suggestion."
    if stance.mode == "disagree":
        return "Disagree clearly but warmly. Give a brief reason; do not lecture or manufacture conflict."
    if stance.mode == "challenge_gently":
        return "Validate the reaction, separate it from the unproven conclusion, and offer a plausible alternative without sounding superior."
    if stance.mode == "partially_agree":
        return "Say which part is fair and which part you see differently. Keep an independent point of view."
    if stance.mode == "agree":
        return "Agree because the evidence supports it, not merely to please the user."
    if stance.mode == "validate_experience":
        return "Treat the feeling as the user's real experience. Do not debate it or automatically endorse external conclusions."
    if stance.mode == "uncertain":
        return "State uncertainty naturally and check available context instead of pretending to agree."
    return _tone_instruction(labels, emotion)


def _listener_first_reason(
    labels: set[str],
    active: TopicState | None,
    emotion: EmotionState,
    stance: ConversationalStance,
) -> str:
    if _stance_requires_attention(stance):
        return stance.reason
    return _plan_reason(labels, active, emotion)


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
    if "confirmation" in labels:
        return "continue_prior_offer"
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
    if "confirmation" in labels:
        return "continue_prior_offer"
    if "simple_ack" in labels:
        return "simple_ack"
    normalized = user_text.casefold()
    if "what should i do" in normalized or "suggest" in normalized or "advice" in normalized:
        return "suggest_solution"
    return "normal_chat"


def _tone_instruction(labels: set[str], emotion: EmotionState) -> str:
    if "confirmation" in labels:
        return "The user confirmed the previous assistant turn. Continue the pending offer/action; do not only acknowledge."
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
