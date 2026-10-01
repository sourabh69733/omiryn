"""Builds the response plan from turn understanding, conversation threads, and user constraints."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from agent.context_engine.contracts.models import (
    ContextQueryIntent,
    ConversationalStance,
    ConversationPlan,
    EmotionState,
    MatchingUnderstanding,
    ThreadGuidance,
    ThreadReference,
)
from agent.memory_engine.memories.vibe import VIBE_AREA_GOALS

COMMON_STARTER_AVOID_TOPICS = (
    "Generic music preference starters.",
    "Generic movie preference starters.",
    "Truth-or-dare game starters.",
    "Repeated how-was-your-day/opening-smalltalk questions.",
)
COMMON_STARTER_TOPIC_POLICY = (
    "Do not start generic music, movie, truth-or-dare, or how-was-your-day topics.",
    "Use common topics only when the user explicitly brings them up, or when tied to a sharper personal angle.",
)
# Fresh angles offered on a low-energy turn: the first open vibe areas.
FRESH_ANGLE_LIMIT = 3


def build_conversation_plan(
    *,
    user_text: str,
    intent: ContextQueryIntent,
    emotion_state: EmotionState | None = None,
    conversational_stance: ConversationalStance | None = None,
    matching_understanding: MatchingUnderstanding | None = None,
    thread_guidance: ThreadGuidance | None = None,
    listener_first: bool = False,
) -> ConversationPlan:
    if listener_first:
        return _build_listener_first_plan(
            user_text=user_text,
            intent=intent,
            emotion_state=emotion_state or EmotionState(),
            stance=conversational_stance or ConversationalStance(),
            matching_understanding=matching_understanding,
            thread_guidance=thread_guidance,
        )
    labels = set(intent.labels)
    active = _active_subject(thread_guidance)
    avoid_topics = _avoid_topics(labels)
    emotion = emotion_state or EmotionState()
    response_mode = _response_mode(user_text, labels, emotion)
    move = _conversation_move(labels, active, emotion)
    return ConversationPlan(
        current_move=move,
        response_mode=response_mode,
        active_topic=active,
        avoid_topics=avoid_topics,
        tone_instruction=_tone_instruction(labels, emotion),
        reason=_plan_reason(labels, active, emotion),
        **_thread_decision(
            intent=intent,
            emotion=emotion,
            stance=conversational_stance or ConversationalStance(),
            guidance=thread_guidance,
        ),
    )


# Purposes a streak may silence; clarify and challenge stay, since they serve the user.
_COOLDOWN_PURPOSES = {"optional", "deepen", "offer_choice"}
_QUESTION_STREAK_LIMIT = 2


def apply_question_cooldown(
    plan: ConversationPlan,
    messages: list[dict[str, Any]],
) -> ConversationPlan:
    """Forbid a question this turn when the last two agent replies both asked one."""
    if plan.question_purpose not in _COOLDOWN_PURPOSES:
        return plan
    if recent_question_streak(messages) < _QUESTION_STREAK_LIMIT:
        return plan
    return replace(plan, question_purpose="none")


def recent_question_streak(messages: list[dict[str, Any]]) -> int:
    """How many of the latest agent replies in a row contained a question.

    Consecutive agent bubbles count as one reply; the streak stops at the first reply
    without a question mark.
    """
    replies: list[str] = []
    previous_role = None
    for message in messages:
        role = message.get("role")
        if role == "assistant":
            text = str(message.get("content") or "")
            if previous_role == "assistant":
                replies[-1] += " " + text
            else:
                replies.append(text)
        previous_role = role
    streak = 0
    for reply in reversed(replies):
        if "?" not in reply:
            break
        streak += 1
    return streak


def _build_listener_first_plan(
    *,
    user_text: str,
    intent: ContextQueryIntent,
    emotion_state: EmotionState,
    stance: ConversationalStance,
    matching_understanding: MatchingUnderstanding | None,
    thread_guidance: ThreadGuidance | None,
) -> ConversationPlan:
    labels = set(intent.labels)
    prioritized = _stance_requires_attention(stance)
    active = None if prioritized else _active_subject(thread_guidance)
    question_purpose = stance.question_purpose
    if question_purpose == "none" and not prioritized and labels & {"low_information", "boredom_complaint"}:
        question_purpose = "offer_choice"
    matching_discovery_allowed = matching_understanding is not None and _matching_discovery_is_allowed(
        emotion_state,
        stance,
        question_purpose,
    )
    return ConversationPlan(
        current_move=_listener_first_move(labels, active, emotion_state, stance),
        response_mode=_listener_first_response_mode(user_text, labels, emotion_state, stance),
        active_topic=active,
        avoid_topics=_avoid_topics(labels),
        suggested_topics=_fresh_angles(labels, prioritized, matching_understanding),
        tone_instruction=_listener_first_tone_instruction(labels, emotion_state, stance),
        reason=_listener_first_reason(labels, active, emotion_state, stance),
        stance=stance.mode,
        stance_confidence=stance.confidence,
        claim_type=stance.claim_type,
        question_purpose=question_purpose,
        user_constraints=stance.constraints,
        feedback_kind=stance.feedback_kind,
        matching_discovery_allowed=matching_discovery_allowed,
        matching_discovery_topics=_matching_discovery_topics(
            matching_understanding,
            allowed=matching_discovery_allowed,
        ),
        **_thread_decision(
            intent=intent,
            emotion=emotion_state,
            stance=stance,
            guidance=thread_guidance,
        ),
    )


def _thread_decision(
    *,
    intent: ContextQueryIntent,
    emotion: EmotionState,
    stance: ConversationalStance,
    guidance: ThreadGuidance | None,
) -> dict[str, str | None]:
    if not guidance or (not guidance.active and not guidance.relevant_open):
        return _thread_fields("none")
    if stance.constraints or stance.feedback_kind or emotion.response_mode != "normal_chat":
        return _thread_fields("follow_user")
    if not intent.is_low_information:
        return _thread_fields("follow_user")
    if guidance.active and _thread_is_engaged(guidance.active):
        return _thread_fields("continue_active", guidance.active)
    candidate = next(
        (thread for thread in guidance.relevant_open if _thread_is_engaged(thread)),
        None,
    )
    if candidate:
        return _thread_fields("offer_open", candidate)
    unengaged = guidance.active or next(iter(guidance.relevant_open), None)
    if unengaged:
        return _thread_fields("ignore_unengaged", unengaged)
    return _thread_fields("none")


def _thread_is_engaged(thread: ThreadReference) -> bool:
    return thread.origin == "user_started" or thread.user_interest in {"medium", "high"}


def _thread_fields(
    action: str,
    thread: ThreadReference | None = None,
) -> dict[str, str | None]:
    return {
        "thread_action": action,
        "thread_id": thread.id if thread else None,
        "thread_title": thread.title if thread else None,
        "thread_next_angle": thread.next_angle if thread else None,
    }


def _matching_discovery_is_allowed(
    emotion: EmotionState,
    stance: ConversationalStance,
    question_purpose: str,
) -> bool:
    """Keep matching discovery out of turns that need attention, safety, or space."""
    if stance.constraints or stance.feedback_kind or stance.mode != "neutral":
        return False
    if emotion.response_mode != "normal_chat":
        return False
    if question_purpose == "none" and stance.claim_type != "none":
        return False
    return True


def _matching_discovery_topics(
    matching_understanding: MatchingUnderstanding | None,
    *,
    allowed: bool,
) -> tuple[str, ...]:
    """Offer private deepening opportunities before entirely unexplored areas."""
    if not matching_understanding or not allowed:
        return ()
    return (
        *matching_understanding.can_deepen_dimensions,
        *matching_understanding.unexplored_dimensions,
    )


def _stance_requires_attention(stance: ConversationalStance) -> bool:
    return bool(
        stance.feedback_kind
        or stance.constraints
        or stance.mode
        in {"agree", "partially_agree", "disagree", "challenge_gently", "validate_experience", "uncertain"}
    )


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
    active: str | None,
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
    active: str | None,
    emotion: EmotionState,
    stance: ConversationalStance,
) -> str:
    if _stance_requires_attention(stance):
        return stance.reason
    return _plan_reason(labels, active, emotion)


def _conversation_move(
    labels: set[str],
    active: str | None,
    emotion: EmotionState,
) -> str:
    if "whatsapp" in labels and "style" in labels:
        return "specific_context_observation"
    if "whatsapp" in labels:
        return "direct_answer_from_context"
    if "adult_flirty" in labels:
        return "warm_boundary"
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
    return "specific_observation"


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
        return "Stay warm and friendly, never flirty. Keep any boundary light and kind, then move on."
    if "boredom_complaint" in labels:
        return "Recover from boredom with a sharper personal or opinion angle. Do not start music, movies, truth-or-dare, or day-check smalltalk."
    if "low_information" in labels:
        return "Bring energy with one fresh playful angle; do not sound like an interview or use generic common topics."
    if "whatsapp" in labels:
        return "Be concrete. Use stored WhatsApp context if available and admit uncertainty only when needed."
    return (
        "React to the specific thing the user said: notice a detail, make a playful guess, or give "
        "your honest take. A question is optional; most replies should not end with one."
    )


def _plan_reason(labels: set[str], active: str | None, emotion: EmotionState) -> str:
    if emotion.emotion != "neutral" and emotion.confidence >= 0.5:
        return f"Emotion={emotion.emotion}; need={emotion.need}; strategy={emotion.strategy}."
    if labels:
        return f"Intent labels: {', '.join(sorted(labels))}."
    if active:
        return f"Continue the active subject: {active}."
    return "Default companion flow."


def _avoid_topics(labels: set[str]) -> tuple[str, ...]:
    avoided: list[str] = []
    for topic in COMMON_STARTER_AVOID_TOPICS:
        if topic not in avoided:
            avoided.append(topic)
    if "common_topic" in labels or "boredom_complaint" in labels:
        for policy in COMMON_STARTER_TOPIC_POLICY:
            if policy not in avoided:
                avoided.append(policy)
    return tuple(avoided)


def _active_subject(guidance: ThreadGuidance | None) -> str | None:
    """The subject the background model is tracking as active; no keyword guessing."""
    if guidance and guidance.active:
        return guidance.active.title
    return None


def _fresh_angles(
    labels: set[str],
    prioritized: bool,
    matching_understanding: MatchingUnderstanding | None,
) -> tuple[str, ...]:
    """On a low-energy turn, what the companion does not know about the user yet."""
    if prioritized or not labels & {"low_information", "boredom_complaint"}:
        return ()
    if not matching_understanding:
        return ()
    return tuple(
        f"Something about {VIBE_AREA_GOALS[area_id]}"
        for area_id in matching_understanding.unexplored_dimensions[:FRESH_ANGLE_LIMIT]
        if area_id in VIBE_AREA_GOALS
    )
