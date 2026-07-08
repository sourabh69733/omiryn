from __future__ import annotations

import re
from typing import Any

from agent.context_engine.utils import normalized_memory_text


CORRECTION_PATTERNS = (
    re.compile(
        r"(?:you are|you're|youre|u r)\s+not\s+(?P<avoid>[^,.]+)[,.\s]+"
        r"(?:you are|you're|youre|u r)\s+(?P<prefer>[^,.]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:do not|don't|dont|never)\s+(?:say|use|write)\s+(?P<avoid>[^,.]+)[,.\s]+"
        r"(?:say|use|write)\s+(?P<prefer>[^,.]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:use|say|write)\s+(?P<prefer>[^,.]+)\s+(?:not|instead of)\s+(?P<avoid>[^,.]+)",
        re.IGNORECASE,
    ),
)

def extract_agent_behavior_rules_from_message(
    *,
    user_id: str,
    conversation_id: str,
    message: str,
    message_index: int,
) -> list[dict[str, Any]]:
    rules = _explicit_correction_rules(user_id, conversation_id, message, message_index)
    rules.extend(_topic_policy_rules(user_id, conversation_id, message, message_index))
    return _dedupe_rules(rules)


def _explicit_correction_rules(
    user_id: str,
    conversation_id: str,
    message: str,
    message_index: int,
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for pattern in CORRECTION_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        avoid = _clean_phrase(match.group("avoid"))
        prefer = _clean_phrase(match.group("prefer"))
        if not avoid or not prefer:
            continue
        category, key, rule_text, priority = _correction_rule_details(avoid, prefer)
        rules.append(
            _rule(
                user_id=user_id,
                conversation_id=conversation_id,
                message=message,
                message_index=message_index,
                category=category,
                key=key,
                rule_text=rule_text,
                avoid_text=avoid,
                prefer_text=prefer,
                priority=priority,
                confidence=0.92,
            )
        )
    return rules


def _topic_policy_rules(
    user_id: str,
    conversation_id: str,
    message: str,
    message_index: int,
) -> list[dict[str, Any]]:
    normalized = normalized_memory_text(message)
    if not (
        any(term in normalized for term in {"boring", "bored", "bore", "repeat", "same"})
        and any(term in normalized for term in {"music", "movie", "movies", "song", "songs"})
    ):
        return []
    return [
        _rule(
            user_id=user_id,
            conversation_id=conversation_id,
            message=message,
            message_index=message_index,
            category="topic_policy",
            key="avoid_generic_music_movie_starters",
            rule_text=(
                "Do not start generic music/movie conversations unless the user brings them up "
                "or they are tied to a sharper dating, memory, personality, or relationship angle."
            ),
            avoid_text="generic music/movie starters",
            prefer_text="specific dating, memory, personality, or relationship angles",
            priority=86,
            confidence=0.84,
        )
    ]


def _correction_rule_details(avoid: str, prefer: str) -> tuple[str, str, str, int]:
    return (
        "user_taught_phrase_rule",
        _key_from_phrase(avoid, prefer),
        (
            f"When replying, avoid \"{avoid}\" and prefer \"{prefer}\". "
            "Apply the same user-taught correction pattern when similar wording appears."
        ),
        92,
    )


def _rule(
    *,
    user_id: str,
    conversation_id: str,
    message: str,
    message_index: int,
    category: str,
    key: str,
    rule_text: str,
    avoid_text: str | None,
    prefer_text: str | None,
    priority: int,
    confidence: float,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "category": category,
        "key": key,
        "rule_text": rule_text,
        "avoid_text": avoid_text,
        "prefer_text": prefer_text,
        "confidence": confidence,
        "priority": priority,
        "source_kind": "agent_chat",
        "source_id": conversation_id,
        "evidence": [
            {
                "source_kind": "agent_chat",
                "source_id": conversation_id,
                "message_index": message_index,
                "quote": message,
            }
        ],
        "status": "active",
    }


def _clean_phrase(value: str) -> str:
    return " ".join(value.strip(" '\"“”‘’").split())[:120]


def _key_from_phrase(avoid: str, prefer: str) -> str:
    key = normalized_memory_text(f"{avoid} {prefer}").replace(" ", "_")
    return key[:80] or "phrase_correction"


def _dedupe_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for rule in rules:
        identity = (str(rule.get("category")), str(rule.get("key")))
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(rule)
    return deduped
