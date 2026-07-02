from __future__ import annotations

from typing import Any

from .config import _provider_name
from .json_utils import _parse_json_object
from .messages import _is_greeting_only, _messages_for_profile_extraction
from .normalization import _normalize_deep_profile_facts
from .prompts import _agent_persona_for_interest


def _mock_reply(
    messages: list[dict[str, str]],
    user_profile: dict[str, Any] | None = None,
    agent_name: str | None = None,
) -> str:
    user_messages = [message for message in messages if message["role"] == "user"]
    persona = _agent_persona_for_interest(str((user_profile or {}).get("interested_in") or ""))
    if agent_name and agent_name.strip():
        persona = {**persona, "name": agent_name.strip()}
    if user_messages and _is_greeting_only(user_messages[-1]["content"]):
        return f"Hey, I'm {persona['name']}. Chill, we can talk normally first."

    prompts = [
        "hmm okay, fair.",
        "haan, that feels clear.",
        "acha, got it.",
        "fair enough, I like that honestly.",
        "sahi hai, keep going.",
    ]
    return prompts[min(len(user_messages), len(prompts) - 1)]

def _mock_deep_profile_facts(
    messages: list[dict[str, str]],
    user_id: str,
    conversation_id: str | None,
) -> list[dict[str, Any]]:
    text = " ".join(
        str(message.get("content", "")).lower()
        for message in _messages_for_profile_extraction(messages)
        if message.get("role") == "user"
    )
    raw_facts = []
    if "career" in text or "growth" in text:
        raw_facts.append(
            {
                "category": "goals",
                "key": "career_growth",
                "label": "Values career growth",
                "value": {
                    "kind": "career_growth",
                    "detail": "User repeatedly mentions career or growth.",
                },
                "confidence": 0.72,
                "evidence": "Mentions career or growth as important.",
            }
        )
    if "respect" in text:
        raw_facts.append(
            {
                "category": "values",
                "key": "mutual_respect",
                "label": "Values mutual respect",
                "value": {"kind": "mutual_respect"},
                "confidence": 0.74,
                "evidence": "Mentions mutual respect.",
            }
        )
    if not raw_facts:
        raw_facts.append(
            {
                "category": "personality",
                "key": "open_to_reflection",
                "label": "Open to reflection",
                "value": {"kind": "open_to_reflection"},
                "confidence": 0.42,
                "evidence": "Continues the onboarding conversation.",
            }
        )
    return _normalize_deep_profile_facts({"facts": raw_facts}, user_id, conversation_id)

def _mock_llm_data_points(extraction_text: str) -> dict[str, Any]:
    text = extraction_text.lower()
    points: list[dict[str, Any]] = []
    if "coffee" in text and "walk" in text:
        points.append(
            {
                "category": "recent_events",
                "key": "coffee_then_walk_plan",
                "label": "Planned coffee then a walk",
                "meaning": "Useful when the user asks what the latest concrete WhatsApp plan was.",
                "value": {"kind": "coffee_then_walk_plan", "detail": "Coffee first, then walk."},
                "confidence": 0.82,
                "evidence": ["coffee first, then walk?"],
                "used_for_chat_context": True,
                "used_for_matching": False,
                "used_for_style": False,
                "privacy_level": "normal",
            }
        )
    if "wahi per rukna" in text or "location" in text:
        points.append(
            {
                "category": "conversation_context",
                "key": "meeting_location_coordination",
                "label": "Coordinated where to wait or meet",
                "meaning": "Useful for answering questions about last WhatsApp location or meeting context.",
                "value": {"kind": "meeting_location_coordination"},
                "confidence": 0.78,
                "evidence": ["wahi per rukna", "location kidhar hai"],
                "used_for_chat_context": True,
                "used_for_matching": False,
                "used_for_style": False,
                "privacy_level": "normal",
            }
        )
    if not points:
        points.append(
            {
                "category": "communication_style",
                "key": "short_casual_whatsapp_style",
                "label": "Uses short casual WhatsApp replies",
                "meaning": "Useful for adapting reply length and rhythm.",
                "value": {"kind": "short_casual_whatsapp_style"},
                "confidence": 0.58,
                "evidence": ["short chat messages"],
                "used_for_chat_context": True,
                "used_for_matching": False,
                "used_for_style": True,
                "privacy_level": "normal",
            }
        )
    return {"data_points": points}

def _mock_llm_data_point_reviews(review_text: str) -> dict[str, Any]:
    try:
        payload = _parse_json_object(review_text)
        candidates = payload.get("candidates") if isinstance(payload, dict) else []
    except Exception:
        candidates = []
    reviews: list[dict[str, Any]] = []
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        key = str(candidate.get("key") or "")
        label = str(candidate.get("label") or "")
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), list) else []
        if "talked about" in label.lower() or not evidence:
            reviews.append(
                {
                    "candidate_key": key,
                    "decision": "reject",
                    "what_we_learned": "",
                    "why_it_matters": "",
                    "confidence": 0.0,
                    "evidence": [],
                    "usage": {"debug_only": True},
                    "final_point": None,
                    "rejection_reason": "Weak keyword-style candidate.",
                }
            )
            continue
        reviews.append(
            {
                "candidate_key": key,
                "decision": "approve",
                "what_we_learned": label,
                "why_it_matters": str(candidate.get("meaning") or "Useful later."),
                "confidence": candidate.get("confidence") or 0.72,
                "evidence": evidence[:3],
                "usage": candidate.get("usage") or {"chat_context": True},
                "final_point": {
                    "category": candidate.get("category") or "conversation_context",
                    "key": key,
                    "label": label,
                    "meaning": candidate.get("meaning") or "Useful later.",
                    "value": candidate.get("value") or {"kind": key},
                    "privacy_level": "normal",
                },
                "rejection_reason": None,
            }
        )
    return {"reviews": reviews}

def _mock_profile(messages: list[dict[str, str]]) -> dict[str, Any]:
    profile_messages = _messages_for_profile_extraction(messages)
    text = " ".join(
        message["content"].lower()
        for message in profile_messages
        if message["role"] == "user"
    )
    city = "Bengaluru" if "bengaluru" in text or "bangalore" in text else "unknown"
    intent = "marriage" if "marriage" in text else "long_term" if "long" in text else "unknown"
    dealbreakers = []
    if "smoking" in text or "smoker" in text:
        dealbreakers.append("smoking")

    return {
        "agent_provider": _provider_name(),
        "display_name": None,
        "age": None,
        "city": {"value": city, "source": "user_stated" if city != "unknown" else "unknown", "confidence": 0.7},
        "relationship_intent": {
            "value": intent,
            "source": "user_stated" if intent != "unknown" else "unknown",
            "confidence": 0.75,
        },
        "values": {
            "values": ["family", "emotional_stability"],
            "source": "inferred",
            "confidence": 0.55,
        },
        "lifestyle": {"values": [], "source": "unknown", "confidence": 0.4},
        "communication_style": {
            "value": "direct",
            "source": "inferred",
            "confidence": 0.5,
        },
        "family_expectations": {
            "value": "unknown",
            "source": "unknown",
            "confidence": 0.4,
        },
        "children_preference": {
            "value": "unknown",
            "source": "unknown",
            "confidence": 0.4,
        },
        "dealbreakers": {
            "values": dealbreakers,
            "source": "user_stated" if dealbreakers else "unknown",
            "confidence": 0.65,
        },
        "soft_preferences": {"values": [], "source": "unknown", "confidence": 0.4},
        "summary": "Draft profile extracted from the Omiryn onboarding conversation.",
    }
