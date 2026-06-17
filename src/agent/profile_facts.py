from __future__ import annotations

import re
from typing import Any


CITY_ALIASES = {
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "mumbai": "Mumbai",
    "delhi": "Delhi",
    "pune": "Pune",
    "hyderabad": "Hyderabad",
    "chennai": "Chennai",
    "kolkata": "Kolkata",
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
    "noida": "Noida",
}

INTENT_PATTERNS = [
    (
        "marriage",
        r"\b(marriage|marry|shaadi)\b",
        "Wants marriage-oriented dating",
        0.82,
    ),
    (
        "long_term",
        r"\b(long[- ]?term|serious relationship|something serious|committed)\b",
        "Wants a serious long-term relationship",
        0.78,
    ),
    (
        "casual",
        r"\b(casual|not serious|no commitment)\b",
        "Is open to casual dating",
        0.72,
    ),
    (
        "exploring",
        r"\b(exploring|figuring out|not sure yet|still deciding)\b",
        "Is still exploring relationship intent",
        0.66,
    ),
]

VALUE_PATTERNS = [
    ("family", r"\b(family|family[- ]?oriented)\b", "Values family orientation"),
    ("ambition", r"\b(ambition|ambitious|career|growth)\b", "Values ambition and growth"),
    (
        "emotional_maturity",
        r"\b(emotional maturity|emotionally mature|emotional stability|stable)\b",
        "Values emotional maturity",
    ),
    ("honesty", r"\b(honesty|honest|truthful|transparent)\b", "Values honesty"),
    ("kindness", r"\b(kindness|kind|compassion)\b", "Values kindness"),
    ("respect", r"\b(respect|respectful|mutual respect)\b", "Values mutual respect"),
    ("independence", r"\b(independent|independence|space)\b", "Values independence"),
]

LIFESTYLE_PATTERNS = [
    ("fitness", r"\b(fitness|gym|workout|running|yoga)\b", "Maintains a fitness-oriented lifestyle"),
    ("travel", r"\b(travel|travelling|trip|trips)\b", "Enjoys travel"),
    ("reading", r"\b(reading|books|book)\b", "Enjoys reading"),
    ("balanced_work", r"\b(work[- ]?life|balanced work|balance)\b", "Values work-life balance"),
    ("vegetarian", r"\b(vegetarian|veg)\b", "Prefers a vegetarian lifestyle"),
]

COMMUNICATION_PATTERNS = [
    ("direct", r"\b(direct|straightforward|clear communication)\b", "Prefers direct communication"),
    (
        "calm_low_drama",
        r"\b(calm|low[- ]?drama|no drama|dramatic fights|drama)\b",
        "Prefers calm, low-drama communication",
    ),
    (
        "thoughtful",
        r"\b(thoughtful conversation|deep conversation|meaningful conversation)\b",
        "Enjoys thoughtful conversations",
    ),
    ("playful", r"\b(humor|funny|playful|jokes|banter)\b", "Enjoys playful communication"),
]

DEALBREAKER_PATTERNS = [
    ("smoking", r"\b(smoking|smoker|cigarette)\b", "Smoking is a dealbreaker"),
    ("heavy_drinking", r"\b(heavy drinking|alcoholic|too much drinking)\b", "Heavy drinking is a dealbreaker"),
    ("dishonesty", r"\b(dishonesty|lying|liar|cheating)\b", "Dishonesty is a dealbreaker"),
    ("high_conflict", r"\b(drama|dramatic fights|toxic fights|shouting)\b", "High-conflict behavior is a dealbreaker"),
    ("disrespect", r"\b(disrespect|rude|insult)\b", "Disrespect is a dealbreaker"),
]

PREFERENCE_PATTERNS = [
    ("calm_partner", r"\b(calm people|calm person|calm partner)\b", "Prefers a calm partner"),
    (
        "family_oriented_partner",
        r"\b(family[- ]?oriented partner|family[- ]?oriented person|family[- ]?oriented people)\b",
        "Prefers a family-oriented partner",
    ),
    ("ambitious_partner", r"\b(ambitious partner|ambitious person)\b", "Prefers an ambitious partner"),
    ("mature_partner", r"\b(mature partner|mature person)\b", "Prefers a mature partner"),
]


def extract_profile_facts_from_message(
    user_id: str,
    conversation_id: str,
    message: str,
    message_index: int,
) -> list[dict[str, Any]]:
    text = message.strip()
    if not text:
        return []

    lowered = text.lower()
    evidence = _evidence(conversation_id, message_index, text)
    facts: list[dict[str, Any]] = []

    for value, pattern, label, confidence in INTENT_PATTERNS:
        if re.search(pattern, lowered):
            facts.append(
                _fact(
                    user_id,
                    "dating_intent",
                    "relationship_intent",
                    {"kind": value},
                    label,
                    confidence,
                    evidence,
                    conversation_id,
                )
            )
            break

    city = _extract_city(lowered)
    if city:
        facts.append(
            _fact(
                user_id,
                "location",
                "city",
                {"city": city},
                f"Is connected to {city}",
                0.7,
                evidence,
                conversation_id,
            )
        )

    facts.extend(
        _pattern_facts(user_id, "values", VALUE_PATTERNS, lowered, evidence, conversation_id)
    )
    facts.extend(
        _pattern_facts(user_id, "lifestyle", LIFESTYLE_PATTERNS, lowered, evidence, conversation_id)
    )
    facts.extend(
        _pattern_facts(
            user_id,
            "communication",
            COMMUNICATION_PATTERNS,
            lowered,
            evidence,
            conversation_id,
        )
    )
    if _has_dealbreaker_language(lowered):
        facts.extend(
            _pattern_facts(
                user_id,
                "dealbreakers",
                DEALBREAKER_PATTERNS,
                lowered,
                evidence,
                conversation_id,
                confidence=0.78,
            )
        )
    facts.extend(
        _pattern_facts(
            user_id,
            "preferences",
            PREFERENCE_PATTERNS,
            lowered,
            evidence,
            conversation_id,
            confidence=0.68,
        )
    )

    return facts


def _pattern_facts(
    user_id: str,
    category: str,
    patterns: list[tuple[str, str, str]],
    text: str,
    evidence: list[dict[str, Any]],
    conversation_id: str,
    confidence: float = 0.72,
) -> list[dict[str, Any]]:
    facts = []
    for key, pattern, label in patterns:
        if re.search(pattern, text):
            facts.append(
                _fact(
                    user_id,
                    category,
                    key,
                    {"kind": key},
                    label,
                    confidence,
                    evidence,
                    conversation_id,
                )
            )
    return facts


def _extract_city(text: str) -> str | None:
    for alias, city in CITY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return city
    return None


def _has_dealbreaker_language(text: str) -> bool:
    return bool(re.search(r"\b(dealbreaker|deal breaker|cannot accept|can't accept|avoid|hate)\b", text))


def _fact(
    user_id: str,
    category: str,
    key: str,
    value: dict[str, Any],
    label: str,
    confidence: float,
    evidence: list[dict[str, Any]],
    conversation_id: str,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "category": category,
        "key": key,
        "value": value,
        "label": label,
        "confidence": confidence,
        "source_kind": "agent_chat",
        "source_id": conversation_id,
        "evidence": evidence,
        "status": "active",
        "visibility": "internal",
        "used_for_matching": True,
    }


def _evidence(conversation_id: str, message_index: int, message: str) -> list[dict[str, Any]]:
    return [
        {
            "conversation_id": conversation_id,
            "message_index": message_index,
            "quote": message[:240],
        }
    ]
