from __future__ import annotations

import re
from typing import Any

from .messages import _user_messages_for_memory_extraction


def _deep_fact_extraction_text(messages: list[dict[str, str]]) -> str:
    profile_messages = _user_messages_for_memory_extraction(messages)
    recent_messages = profile_messages[-24:]
    conversation_text = "\n".join(
        f"user[{message.get('message_index', '-')}]: {message.get('content', '')}"
        for message in recent_messages
        if message.get("content")
    )
    return (
        "User messages for fact extraction. Extract durable matching facts only from "
        "these user-authored lines. Never use assistant replies as evidence.\n\n"
        f"{conversation_text}"
    )

def _normalize_deep_profile_facts(
    raw: dict[str, Any],
    user_id: str,
    conversation_id: str | None,
) -> list[dict[str, Any]]:
    raw_facts = raw.get("facts")
    if not isinstance(raw_facts, list):
        return []

    facts = []
    for index, raw_fact in enumerate(raw_facts[:30]):
        if not isinstance(raw_fact, dict):
            continue
        fact = _normalize_deep_profile_fact(raw_fact, user_id, conversation_id, index)
        if fact:
            facts.append(fact)
    return facts

def _normalize_deep_profile_fact(
    raw_fact: dict[str, Any],
    user_id: str,
    conversation_id: str | None,
    index: int,
) -> dict[str, Any] | None:
    category = _snake_key(str(raw_fact.get("category") or "other")) or "other"
    label = str(raw_fact.get("label") or raw_fact.get("key") or "").strip()
    key = _snake_key(str(raw_fact.get("key") or label or f"deep_fact_{index + 1}"))
    if not key or not label:
        return None

    value = raw_fact.get("value")
    if not isinstance(value, dict):
        value = {"kind": key, "detail": str(value or label)}
    value.setdefault("kind", key)

    evidence_text = str(raw_fact.get("evidence") or label).strip()
    confidence = _safe_confidence(raw_fact.get("confidence"), 0.55)
    return {
        "user_id": user_id,
        "category": category[:80],
        "key": key[:120],
        "value": value,
        "label": label[:160],
        "confidence": confidence,
        "source_kind": "agent_deep_memory",
        "source_id": conversation_id,
        "evidence": [
            {
                "conversation_id": conversation_id,
                "message_index": None,
                "text": evidence_text[:320],
            }
        ],
        "status": "active",
        "visibility": "internal",
        "used_for_matching": True,
    }

def _snake_key(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")

def _safe_confidence(value: Any, fallback: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = fallback
    return max(0.0, min(0.95, confidence))
