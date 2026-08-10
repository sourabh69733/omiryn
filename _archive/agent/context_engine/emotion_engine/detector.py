from __future__ import annotations

from typing import Any

from agent.context_engine.models import ContextQueryIntent, EmotionState
from agent.context_engine.utils import normalized_memory_text


FRUSTRATION_PHRASES = {
    "you are not listening",
    "u are not listening",
    "you dont understand",
    "you don't understand",
    "you are boring",
    "u are boring",
    "boring me",
    "same question",
    "same questions",
    "stop suggesting",
    "dont suggest",
    "don't suggest",
}
SAD_TERMS = {"sad", "upset", "cry", "cried", "heavy", "broken", "depressed", "low"}
LONELY_TERMS = {"lonely", "alone", "empty", "miss", "missing"}
HURT_TERMS = {"hurt", "ignored", "rejected", "betrayed", "disappointed"}
ANXIOUS_TERMS = {"anxious", "scared", "afraid", "worried", "tension", "panic", "dar"}
CONFUSED_TERMS = {"confused", "confuse", "samajh", "unclear", "lost"}
POSITIVE_TERMS = {"happy", "excited", "nice", "great", "awesome", "wow"}
PLAYFUL_TERMS = {"haha", "lol", "lmao", "hehe", "funny"}
ADVICE_REQUEST_PHRASES = {"what should i do", "kya karu", "kya karun", "suggest", "advice"}


def detect_emotion_state(
    *,
    user_text: str,
    messages: list[dict[str, Any]],
    intent: ContextQueryIntent,
) -> EmotionState:
    normalized = normalized_memory_text(user_text)
    terms = set(normalized.split())
    evidence: list[str] = []

    if "boredom_complaint" in intent.labels or _contains_phrase(normalized, FRUSTRATION_PHRASES):
        evidence.append("User complains about boredom, repetition, or not being understood.")
        return EmotionState(
            emotion="frustrated",
            intensity="medium",
            confidence=0.84,
            need="acknowledgment_and_change",
            strategy="acknowledge_then_adjust",
            response_mode="apologize_and_adjust",
            evidence=tuple(evidence),
        )

    if terms & HURT_TERMS:
        evidence.append("User uses hurt/rejection language.")
        return _emotional_state("hurt", "validation", "listen_first", evidence, normalized)
    if terms & LONELY_TERMS:
        evidence.append("User uses loneliness/missing language.")
        return _emotional_state("lonely", "presence", "listen_first", evidence, normalized)
    if terms & SAD_TERMS:
        evidence.append("User uses sadness/low mood language.")
        return _emotional_state("sad", "validation", "listen_first", evidence, normalized)
    if terms & ANXIOUS_TERMS:
        evidence.append("User uses anxiety/fear language.")
        return _emotional_state("anxious", "reassurance", "slow_down", evidence, normalized)
    if terms & CONFUSED_TERMS:
        evidence.append("User indicates confusion.")
        return EmotionState(
            emotion="confused",
            intensity="low",
            confidence=0.7,
            need="clarity",
            strategy="clarify_gently",
            response_mode="clarify",
            evidence=tuple(evidence),
        )
    if terms & POSITIVE_TERMS:
        evidence.append("User shows positive energy.")
        return EmotionState(
            emotion="excited",
            intensity="low",
            confidence=0.62,
            need="shared_energy",
            strategy="celebrate",
            response_mode="celebrate",
            evidence=tuple(evidence),
        )
    if terms & PLAYFUL_TERMS:
        evidence.append("User is playful.")
        return EmotionState(
            emotion="playful",
            intensity="low",
            confidence=0.62,
            need="play_along",
            strategy="play_along",
            response_mode="playful",
            evidence=tuple(evidence),
        )

    contextual_state = _recent_context_emotion(messages)
    if contextual_state:
        return contextual_state
    return EmotionState()


def _emotional_state(
    emotion: str,
    need: str,
    strategy: str,
    evidence: list[str],
    normalized: str,
) -> EmotionState:
    wants_advice = _contains_phrase(normalized, ADVICE_REQUEST_PHRASES)
    return EmotionState(
        emotion=emotion,
        intensity="medium",
        confidence=0.74,
        need=need if not wants_advice else "advice_after_validation",
        strategy=strategy if not wants_advice else "validate_then_suggest",
        response_mode="empathize_listen" if not wants_advice else "validate_then_suggest",
        evidence=tuple(evidence),
    )


def _recent_context_emotion(messages: list[dict[str, Any]]) -> EmotionState | None:
    recent = messages[-6:]
    user_messages = [
        normalized_memory_text(str(message.get("content") or ""))
        for message in recent
        if message.get("role") == "user"
    ]
    if len(user_messages) >= 2 and all(text in {"hmm", "ok", "okay", "haan"} for text in user_messages[-2:]):
        return EmotionState(
            emotion="low_energy",
            intensity="low",
            confidence=0.55,
            need="more_engaging_flow",
            strategy="gentle_energy_shift",
            response_mode="playful_recover",
            evidence=("Recent user replies are short/low-energy.",),
        )
    return None


def _contains_phrase(normalized: str, phrases: set[str]) -> bool:
    return any(normalized_memory_text(phrase) in normalized for phrase in phrases)
