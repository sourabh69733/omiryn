from __future__ import annotations

from typing import Any

from agent.context_engine.models import ConversationalStance, EmotionState
from agent.context_engine.utils import normalized_memory_text


NO_ADVICE_PHRASES = {
    "don't give advice",
    "dont give advice",
    "do not give advice",
    "don't want advice",
    "dont want advice",
    "do not want advice",
    "no advice",
    "advice mat",
    "suggestion mat",
    "suggest mat",
    "solution mat",
}
NO_QUESTION_PHRASES = {
    "don't ask questions",
    "dont ask questions",
    "do not ask questions",
    "don't ask me anything",
    "dont ask me anything",
    "do not ask me anything",
    "no questions",
    "question mat",
    "questions mat",
    "sawal mat",
    "kuch mat pucho",
    "kuch mat puchna",
}
LISTEN_ONLY_PHRASES = {
    "just listen",
    "bas suno",
    "bas meri baat suno",
    "just stay with me",
    "bas saath raho",
}
GIVE_SPACE_PHRASES = {
    "leave me alone",
    "give me space",
    "don't want to talk",
    "dont want to talk",
    "do not want to talk",
    "baat nahi karni",
    "abhi baat nahi",
    "not now",
}
QUESTION_OVERLOAD_PHRASES = {
    "too many questions",
    "every reply question",
    "every reply has a question",
    "har reply mein question",
    "har reply me question",
    "question kyun puch",
    "questions kyun puch",
    "questions puch rahe",
    "questions puch rahi",
    "sawal kyun puch",
    "interview jaisa",
    "interview jaise",
    "interview lag raha",
    "interview lag rahi",
    "stop asking questions",
}
NOT_LISTENING_PHRASES = {
    "you are not listening",
    "u are not listening",
    "you dont understand",
    "you do not understand",
    "tum sun nahi",
    "samajh nahi rahe",
    "samajh nahi rahi",
}
DEMANDED_AGREEMENT_PHRASES = {
    "agree karo",
    "just agree",
    "agree with me",
    "meri haan mein haan",
}
SELF_CERTAINTY_PHRASES = {
    "i am never wrong",
    "im never wrong",
    "i m never wrong",
    "main kabhi galat nahi",
    "i am always right",
    "im always right",
    "main hamesha sahi",
}
UNSUPPORTED_ATTRIBUTION_TERMS = {
    "jealous",
    "hates me",
    "hate me",
    "doesn't care",
    "doesnt care",
    "does not care",
    "don't care about me",
    "dont care about me",
    "trying to hurt me",
}
INFERENCE_MARKERS = {"so", "means", "must be", "obviously", "matlab", "pakka"}
FEELING_PHRASES = {
    "i feel",
    "i felt",
    "mujhe feel",
    "hurt hua",
    "hurt hui",
    "i am sad",
    "im sad",
    "i am lonely",
    "im lonely",
    "i feel ignored",
}
FIRST_PERSON_MARKERS = {"i ", "im ", "i am ", "mujhe ", "mera ", "meri ", "main "}


def analyze_conversational_stance(
    user_text: str,
    messages: list[dict[str, Any]],
    *,
    emotion_state: EmotionState | None = None,
) -> ConversationalStance:
    normalized = normalized_memory_text(user_text)
    constraints = _explicit_constraints(normalized)
    feedback_kind = _feedback_kind(normalized)

    if feedback_kind:
        mode, confidence, evidence = _feedback_stance(feedback_kind, normalized, messages)
        return ConversationalStance(
            mode=mode,
            confidence=confidence,
            claim_type="agent_behavior_feedback",
            question_purpose=_question_purpose_for_feedback(mode, constraints),
            constraints=constraints,
            feedback_kind=feedback_kind,
            reason="Evaluate the feedback against recent behavior, accept the valid part, and adjust without passive obedience.",
            evidence=evidence,
        )

    if _contains_any(normalized, DEMANDED_AGREEMENT_PHRASES) and _contains_any(
        normalized, SELF_CERTAINTY_PHRASES
    ):
        return ConversationalStance(
            mode="disagree",
            confidence=0.96,
            claim_type="demanded_agreement",
            question_purpose="none",
            constraints=constraints,
            reason="The user demands agreement with an absolute self-claim; maintain an independent, respectful view.",
            evidence=("Demanded agreement and an absolute claim appear together.",),
        )

    if _unsupported_attribution(normalized):
        return ConversationalStance(
            mode="challenge_gently",
            confidence=0.86,
            claim_type="unsupported_attribution",
            question_purpose="none" if "no_questions" in constraints else "challenge",
            constraints=constraints,
            reason="Validate the user's reaction but do not accept an unproven motive as fact.",
            evidence=("A causal motive is asserted without supporting evidence.",),
        )

    if _is_personal_feeling(normalized, emotion_state):
        return ConversationalStance(
            mode="validate_experience",
            confidence=0.9,
            claim_type="personal_feeling",
            question_purpose="none" if constraints else "deepen",
            constraints=constraints,
            reason="A personal feeling is not a factual claim to debate; acknowledge the experience.",
            evidence=("The user describes their own feeling or internal experience.",),
        )

    if _absolute_agent_claim(normalized):
        return ConversationalStance(
            mode="uncertain",
            confidence=0.68,
            claim_type="absolute_agent_claim",
            question_purpose="none" if "no_questions" in constraints else "clarify",
            constraints=constraints,
            reason="Check the absolute claim against available conversation or memory before agreeing.",
            evidence=("The user makes an absolute claim about the agent using always/never/everything language.",),
        )

    if constraints:
        return ConversationalStance(
            mode="validate_experience" if set(constraints) & {"no_advice", "listen_only"} else "neutral",
            confidence=0.92,
            claim_type="explicit_boundary",
            question_purpose="none",
            constraints=constraints,
            reason="Honor the user's explicit conversational boundary before choosing content.",
            evidence=("The user states an explicit response constraint.",),
        )

    if _is_direct_question(user_text):
        return ConversationalStance(
            mode="neutral",
            confidence=0.8,
            claim_type="direct_question",
            question_purpose="none",
            reason="Answer the user's question directly before considering any follow-up question.",
        )

    if _is_meaningful_personal_disclosure(normalized):
        return ConversationalStance(
            mode="neutral",
            confidence=0.62,
            claim_type="personal_disclosure",
            question_purpose="deepen",
            reason="The user shared something personal; one specific follow-up may deepen the active thread.",
        )

    return ConversationalStance()


def _explicit_constraints(normalized: str) -> tuple[str, ...]:
    constraints: list[str] = []
    if _contains_any(normalized, NO_ADVICE_PHRASES):
        constraints.append("no_advice")
    if _contains_any(normalized, NO_QUESTION_PHRASES):
        constraints.append("no_questions")
    if _contains_any(normalized, LISTEN_ONLY_PHRASES):
        constraints.append("listen_only")
    if _contains_any(normalized, GIVE_SPACE_PHRASES):
        constraints.append("give_space")
    return tuple(constraints)


def _feedback_kind(normalized: str) -> str | None:
    if _contains_any(normalized, QUESTION_OVERLOAD_PHRASES):
        return "question_overload"
    if _contains_any(normalized, NOT_LISTENING_PHRASES):
        return "not_listening"
    return None


def _feedback_stance(
    feedback_kind: str,
    normalized: str,
    messages: list[dict[str, Any]],
) -> tuple[str, float, tuple[str, ...]]:
    if feedback_kind != "question_overload" or not _has_absolute_question_claim(normalized):
        return "partially_agree", 0.72, ("The user reports an undesirable conversational experience.",)

    assistant_messages = [
        str(message.get("content") or "")
        for message in messages[-10:]
        if message.get("role") == "assistant"
    ]
    if len(assistant_messages) < 2:
        return "uncertain", 0.55, ("There is not enough recent assistant history to verify the frequency claim.",)
    question_count = sum("?" in message for message in assistant_messages)
    ratio = question_count / len(assistant_messages)
    evidence = (
        f"Recent assistant questions: {question_count}/{len(assistant_messages)} replies.",
    )
    if ratio >= 0.85:
        return "agree", 0.92, evidence
    if ratio >= 0.35:
        return "partially_agree", 0.88, evidence
    return "disagree", 0.92, evidence


def _question_purpose_for_feedback(mode: str, constraints: tuple[str, ...]) -> str:
    # Do not answer a complaint about question overload with another question.
    # Feedback should be addressed directly even when the frequency claim is inaccurate.
    return "none"


def _has_absolute_question_claim(normalized: str) -> bool:
    return any(
        phrase in normalized
        for phrase in ("every reply", "har reply", "always ask", "hamesha question")
    )


def _unsupported_attribution(normalized: str) -> bool:
    return _contains_any(normalized, UNSUPPORTED_ATTRIBUTION_TERMS) and _contains_any(
        normalized, INFERENCE_MARKERS
    )


def _is_personal_feeling(normalized: str, emotion_state: EmotionState | None) -> bool:
    if _contains_any(normalized, FEELING_PHRASES):
        return True
    return bool(
        emotion_state
        and emotion_state.emotion in {"hurt", "lonely", "sad", "anxious"}
        and emotion_state.confidence >= 0.5
    )


def _absolute_agent_claim(normalized: str) -> bool:
    agent_reference = any(term in normalized.split() for term in {"you", "tum", "aap"})
    absolute = any(
        phrase in normalized
        for phrase in ("always", "never", "every reply", "har reply", "kuch bhi", "kabhi bhi", "hamesha")
    )
    return agent_reference and absolute


def _is_direct_question(user_text: str) -> bool:
    return "?" in user_text


def _is_meaningful_personal_disclosure(normalized: str) -> bool:
    return len(normalized.split()) >= 5 and any(marker in f"{normalized} " for marker in FIRST_PERSON_MARKERS)


def _contains_any(normalized: str, phrases: set[str]) -> bool:
    return any(normalized_memory_text(phrase) in normalized for phrase in phrases)
