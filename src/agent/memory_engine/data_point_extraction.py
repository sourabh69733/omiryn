from __future__ import annotations

import logging
import os
import re
from typing import Any
import json

from agent.memory_engine.data_points import normalize_data_point
from agent.memory_engine.whatsapp_data_points import extract_whatsapp_data_point_candidates
from agent.runtime.providers import (
    extract_deep_profile_facts,
    extract_llm_data_point_candidates,
    review_llm_data_point_candidates,
)
from ingestion.whatsapp import WhatsappStructuredMemory
from storage import save_data_point_extraction_debug, upsert_profile_fact

logger = logging.getLogger(__name__)

LLM_CONTEXT_CHAR_LIMIT = int(os.getenv("DATA_POINT_LLM_CONTEXT_CHAR_LIMIT", "9000"))
LLM_MAX_POINTS = int(os.getenv("DATA_POINT_LLM_MAX_POINTS", "12"))
VALID_CATEGORIES = {
    "conversation_context",
    "relationship_intent",
    "communication_style",
    "tone_traits",
    "important_people",
    "recent_events",
    "preferences",
    "boundaries",
    "matching_signals",
    "dating_intent",
    "location",
    "values",
    "goals",
    "communication",
    "dealbreakers",
    "personality",
    "whatsapp_recurring_topics",
    "whatsapp_recent_events",
    "whatsapp_tone_traits",
}
VALID_REVIEW_DECISIONS = {"approve", "rewrite", "merge", "reject"}


def data_point_extractor_mode() -> str:
    mode = os.getenv("DATA_POINT_EXTRACTOR", "rules").strip().lower()
    if mode in {"llm", "hybrid", "rules"}:
        return mode
    return "rules"


def should_run_llm_data_point_extraction() -> bool:
    return data_point_extractor_mode() == "llm"


def should_run_hybrid_data_point_review() -> bool:
    return data_point_extractor_mode() == "hybrid"


async def review_rule_data_point_candidates(
    memory: WhatsappStructuredMemory,
    candidates: list[dict[str, Any]],
    *,
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
    conversation_id: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    return await review_data_point_candidates(
        candidates,
        source_excerpt=_whatsapp_data_point_prompt(memory, title),
        source_title=title,
        selected_sender=memory.metadata.get("selected_sender") or "unknown",
        user_id=user_id,
        source_id=source_id,
        import_id=import_id,
        source_kind="whatsapp_import",
        conversation_id=conversation_id,
        model=model,
    )


async def review_data_point_candidates(
    candidates: list[dict[str, Any]],
    *,
    source_excerpt: str,
    source_title: str,
    selected_sender: str | None,
    user_id: str,
    source_id: str,
    import_id: str | None,
    source_kind: str,
    conversation_id: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    raw = await review_llm_data_point_candidates(
        build_data_point_candidate_review_prompt(
            candidates,
            source_excerpt=source_excerpt,
            source_title=source_title,
            selected_sender=selected_sender,
        ),
        conversation_id=conversation_id,
        model=model,
    )
    return normalize_llm_data_point_reviews(
        raw,
        candidates,
        user_id,
        source_id,
        import_id,
        source_title,
        source_kind=source_kind,
    )


async def capture_hybrid_conversation_data_points(
    messages: list[dict[str, object]],
    *,
    user_id: str,
    conversation_id: str,
    model: str | None = None,
) -> None:
    if not should_run_hybrid_data_point_review():
        return
    try:
        proposed_facts = await extract_deep_profile_facts(
            messages,  # type: ignore[arg-type]
            user_id,
            conversation_id=conversation_id,
            model=model,
        )
        candidates = []
        for fact in proposed_facts:
            candidate = _profile_fact_candidate(fact, conversation_id)
            if candidate:
                candidates.append(candidate)
        if not candidates:
            return
        reviews = await review_data_point_candidates(
            candidates,
            source_excerpt=_conversation_data_point_excerpt(messages),
            source_title="In-app conversation",
            selected_sender=None,
            user_id=user_id,
            source_id=conversation_id,
            import_id=None,
            source_kind="agent_conversation",
            conversation_id=conversation_id,
            model=model,
        )
        for review in reviews:
            save_data_point_extraction_debug(
                {
                    "user_id": user_id,
                    "source_kind": "agent_conversation",
                    "source_id": conversation_id,
                    "import_id": None,
                    "candidate_key": review["candidate_key"],
                    "decision": review["decision"],
                    "candidate": review["candidate"],
                    "review": review["review"],
                    "metadata": {
                        "title": "In-app conversation",
                        "extractor": "hybrid_conversation_review",
                    },
                }
            )
            if review.get("point"):
                upsert_profile_fact(normalize_data_point(review["point"]))
    except Exception:
        logger.exception("agent.data_points.hybrid_conversation_failed conversation_id=%s", conversation_id)


async def capture_llm_whatsapp_data_points(
    memory: WhatsappStructuredMemory,
    *,
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
    conversation_id: str | None = None,
    model: str | None = None,
) -> None:
    if not should_run_llm_data_point_extraction():
        return
    try:
        raw = await extract_llm_data_point_candidates(
            _whatsapp_data_point_prompt(memory, title),
            conversation_id=conversation_id,
            model=model,
        )
        for point in normalize_llm_data_points(raw, user_id, source_id, import_id, title):
            upsert_profile_fact(normalize_data_point(point))
    except Exception:
        logger.exception("agent.data_points.llm_capture_failed source_id=%s", source_id)


async def capture_hybrid_whatsapp_data_points(
    memory: WhatsappStructuredMemory,
    *,
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
    conversation_id: str | None = None,
    model: str | None = None,
) -> None:
    if not should_run_hybrid_data_point_review():
        return
    try:
        candidates = extract_whatsapp_data_point_candidates(
            memory,
            source_id=source_id,
            title=title,
        )
        if not candidates:
            return
        reviews = await review_rule_data_point_candidates(
            memory,
            candidates,
            user_id=user_id,
            source_id=source_id,
            import_id=import_id,
            title=title,
            conversation_id=conversation_id,
            model=model,
        )
        for review in reviews:
            save_data_point_extraction_debug(
                {
                    "user_id": user_id,
                    "source_kind": "whatsapp_import",
                    "source_id": source_id,
                    "import_id": import_id,
                    "candidate_key": review["candidate_key"],
                    "decision": review["decision"],
                    "candidate": review["candidate"],
                    "review": review["review"],
                    "metadata": {
                        "title": title,
                        "extractor": "hybrid_llm_review",
                    },
                }
            )
            if review.get("point"):
                upsert_profile_fact(normalize_data_point(review["point"]))
    except Exception:
        logger.exception("agent.data_points.hybrid_capture_failed source_id=%s", source_id)


def normalize_llm_data_points(
    raw: dict[str, Any],
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
    source_kind: str = "whatsapp_import",
) -> list[dict[str, Any]]:
    raw_points = raw.get("data_points") or raw.get("points")
    if not isinstance(raw_points, list):
        return []

    points: list[dict[str, Any]] = []
    for index, raw_point in enumerate(raw_points[:LLM_MAX_POINTS]):
        if not isinstance(raw_point, dict):
            continue
        point = _normalize_llm_data_point(
            raw_point,
            user_id,
            source_id,
            import_id,
            title,
            index,
            source_kind=source_kind,
        )
        if point:
            points.append(point)
    return _dedupe_llm_points(points)


def normalize_llm_data_point_reviews(
    raw: dict[str, Any],
    candidates: list[dict[str, Any]],
    user_id: str,
    source_id: str,
    import_id: str | None,
    title: str,
    source_kind: str = "whatsapp_import",
) -> list[dict[str, Any]]:
    candidate_map = {str(candidate.get("key") or ""): candidate for candidate in candidates}
    raw_reviews = raw.get("reviews")
    if not isinstance(raw_reviews, list):
        return []

    reviews: list[dict[str, Any]] = []
    for index, raw_review in enumerate(raw_reviews):
        if not isinstance(raw_review, dict):
            continue
        review = _normalize_llm_data_point_review(
            raw_review,
            candidate_map,
            user_id,
            source_id,
            import_id,
            title,
            index,
            source_kind,
        )
        if review:
            reviews.append(review)
    return reviews


def _normalize_llm_data_point(
    raw: dict[str, Any],
    user_id: str,
    source_id: str,
    import_id: str | None,
    title: str,
    index: int,
    *,
    source_kind: str = "whatsapp_import",
) -> dict[str, Any] | None:
    category = _snake_key(str(raw.get("category") or "conversation_context"))
    if category not in VALID_CATEGORIES:
        category = "conversation_context"

    label = _clean_text(raw.get("label"), 160)
    meaning = _clean_text(raw.get("meaning"), 240)
    evidence = _evidence_items(raw.get("evidence"))
    confidence = _confidence(raw.get("confidence"), default=0.55)
    if not _valid_llm_point(label, meaning, evidence, confidence):
        return None
    if category in {"dating_intent", "relationship_intent"} and _is_generic_dating_intent(
        label,
        meaning,
        evidence,
    ):
        return None

    key = _snake_key(str(raw.get("key") or label or f"llm_data_point_{index + 1}"))[
        :120
    ]
    value = raw.get("value") if isinstance(raw.get("value"), dict) else {}
    value = {
        **value,
        "kind": _snake_key(str(value.get("kind") or key)) or key,
        "meaning": meaning,
        "title": title,
        "context_source_id": source_id,
        "import_id": import_id,
        "privacy_level": _privacy_level(raw.get("privacy_level")),
        "extractor": "llm",
    }

    return {
        "user_id": user_id,
        "category": category,
        "key": key,
        "value": value,
        "label": label,
        "confidence": confidence,
        "source_kind": source_kind,
        "source_id": source_id,
        "evidence": [
            {
                "context_source_id": source_id,
                "import_id": import_id,
                "text": item,
            }
            for item in evidence[:5]
        ],
        "status": "active",
        "visibility": "internal",
        "used_for_matching": bool(raw.get("used_for_matching", False)),
        "used_for_chat_context": bool(raw.get("used_for_chat_context", True)),
    }


def _normalize_llm_data_point_review(
    raw: dict[str, Any],
    candidate_map: dict[str, dict[str, Any]],
    user_id: str,
    source_id: str,
    import_id: str | None,
    title: str,
    index: int,
    source_kind: str,
) -> dict[str, Any] | None:
    candidate_key = str(raw.get("candidate_key") or "").strip()
    candidate = candidate_map.get(candidate_key)
    if not candidate:
        return None

    decision = _snake_key(str(raw.get("decision") or "reject"))
    if decision not in VALID_REVIEW_DECISIONS:
        decision = "reject"

    evidence = _evidence_items(raw.get("evidence")) or _evidence_items(candidate.get("evidence"))
    confidence = _confidence(raw.get("confidence"), default=_confidence(candidate.get("confidence"), default=0.55))
    what_we_learned = _clean_text(raw.get("what_we_learned"), 240)
    why_it_matters = _clean_text(raw.get("why_it_matters"), 320)
    rejection_reason = _clean_text(raw.get("rejection_reason"), 240)
    usage = _normalize_review_usage(raw.get("usage"), candidate.get("usage"))

    review = {
        "candidate_key": candidate_key,
        "decision": decision,
        "what_we_learned": what_we_learned,
        "why_it_matters": why_it_matters,
        "confidence": confidence,
        "evidence": evidence[:5],
        "usage": usage,
        "rejection_reason": rejection_reason or None,
    }

    if decision == "reject":
        if not rejection_reason:
            return None
        return {
            "candidate_key": candidate_key,
            "decision": "reject",
            "candidate": candidate,
            "review": review,
            "point": None,
        }

    raw_final = raw.get("final_point")
    if not isinstance(raw_final, dict):
        if decision != "approve":
            return None
        raw_final = _candidate_as_final_point(candidate)
    final_point = {
        **raw_final,
        "confidence": confidence,
        "evidence": evidence,
        "used_for_chat_context": usage["chat_context"],
        "used_for_matching": usage["matching"],
    }
    if usage["debug_only"]:
        final_point["used_for_chat_context"] = False
        final_point["used_for_matching"] = False

    point = _normalize_llm_data_point(
        final_point,
        user_id,
        source_id,
        import_id,
        title,
        index,
        source_kind=source_kind,
    )
    if not point:
        return None
    point["value"] = {
        **point["value"],
        "extractor": "hybrid_llm_review",
        "llm_review": review,
        "rule_candidate": candidate,
        "used_for_style": usage["style"],
    }
    return {
        "candidate_key": candidate_key,
        "decision": decision,
        "candidate": candidate,
        "review": {**review, "final_point": raw_final},
        "point": point,
    }


def _whatsapp_data_point_prompt(memory: WhatsappStructuredMemory, title: str) -> str:
    messages = "\n".join(
        _message_line(index, message)
        for index, message in enumerate(_sample_messages(memory))
        if message.content.strip()
    )
    style = "\n".join(
        f"- {profile.sender}: summary={profile.summary}; samples={profile.sample_messages[:3]}"
        for profile in memory.style_profiles[:4]
    )
    text = (
        f"Source title: {title}\n"
        f"Selected sender: {memory.metadata.get('selected_sender') or 'unknown'}\n\n"
        "Sender style summaries:\n"
        f"{style or 'none'}\n\n"
        "WhatsApp messages:\n"
        f"{messages}"
    )
    return text[:LLM_CONTEXT_CHAR_LIMIT]


def build_data_point_review_prompt(
    memory: WhatsappStructuredMemory,
    candidates: list[dict[str, Any]],
    title: str,
) -> str:
    return build_data_point_candidate_review_prompt(
        candidates,
        source_excerpt=_whatsapp_data_point_prompt(memory, title),
        source_title=title,
        selected_sender=memory.metadata.get("selected_sender") or "unknown",
    )


def build_data_point_candidate_review_prompt(
    candidates: list[dict[str, Any]],
    *,
    source_excerpt: str,
    source_title: str,
    selected_sender: str | None,
) -> str:
    payload = {
        "source_title": source_title,
        "selected_sender": selected_sender or "unknown",
        "source_excerpt": source_excerpt[:LLM_CONTEXT_CHAR_LIMIT],
        "candidates": candidates[:LLM_MAX_POINTS],
    }
    return json.dumps(payload, ensure_ascii=False)


def _profile_fact_candidate(
    fact: dict[str, Any],
    conversation_id: str,
) -> dict[str, Any] | None:
    label = _clean_text(fact.get("label") or fact.get("key"), 160)
    key = _snake_key(str(fact.get("key") or label))
    if not key or not label:
        return None
    evidence = [
        item.get("text") if isinstance(item, dict) else str(item)
        for item in (fact.get("evidence") or [])
    ]
    evidence = _evidence_items(evidence)
    value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
    meaning = _clean_text(
        value.get("meaning") or value.get("detail") or f"Useful context learned from this conversation: {label}",
        240,
    )
    return {
        "category": fact.get("category") or "conversation_context",
        "key": key,
        "label": label,
        "meaning": meaning,
        "value": value,
        "confidence": fact.get("confidence") or 0.55,
        "evidence": evidence[:5],
        "usage": {
            "chat_context": bool(fact.get("used_for_chat_context", True)),
            "matching": bool(fact.get("used_for_matching", True)),
            "style": False,
            "debug_only": False,
        },
        "source": {
            "kind": "agent_conversation",
            "conversation_id": conversation_id,
        },
    }


def _conversation_data_point_excerpt(messages: list[dict[str, object]]) -> str:
    recent_messages = [
        message
        for message in messages[-24:]
        if message.get("role") in {"user", "assistant"} and message.get("content")
    ]
    lines = [
        f"{message.get('role', 'unknown')}: {' '.join(str(message.get('content') or '').split())}"
        for message in recent_messages
    ]
    return "\n".join(lines)[:LLM_CONTEXT_CHAR_LIMIT]


def _sample_messages(memory: WhatsappStructuredMemory) -> list[Any]:
    if len(memory.messages) <= 80:
        return memory.messages
    head = memory.messages[:20]
    tail = memory.messages[-60:]
    return head + tail


def _message_line(index: int, message: Any) -> str:
    timestamp = f"{message.timestamp_text} " if message.timestamp_text else ""
    return f"[{index}] {timestamp}{message.sender}: {' '.join(message.content.split())}"


def _valid_llm_point(
    label: str,
    meaning: str,
    evidence: list[str],
    confidence: float,
) -> bool:
    if not label or not meaning or not evidence:
        return False
    if confidence < 0.5:
        return False
    weak_phrases = {"talked about", "mentioned", "chat includes", "topics include"}
    lowered = label.lower()
    if any(phrase in lowered for phrase in weak_phrases):
        return False
    return True


SPECIFIC_DATING_INTENT_PATTERNS = [
    r"\bmarriage\b",
    r"\bmarry\b",
    r"\bshaadi\b",
    r"\blong[- ]?term\b",
    r"\bshort[- ]?term\b",
    r"\bserious\b",
    r"\bcommitted\b",
    r"\bcommitment\b",
    r"\bcasual\b",
    r"\bexploring\b",
    r"\bfiguring out\b",
    r"\bnot sure yet\b",
    r"\bno commitment\b",
]


GENERIC_DATING_INTENT_PHRASES = {
    "looking for someone",
    "someone special",
    "looking for dating",
    "interested in dating",
    "open to relationship",
    "open to a relationship",
    "wants a relationship",
    "wants dating",
    "wants a partner",
    "looking for a partner",
    "talks about dating",
    "talks about relationship",
}


def _is_generic_dating_intent(
    label: str,
    meaning: str,
    evidence: list[str],
) -> bool:
    text = " ".join([label, meaning, *evidence]).lower()
    if any(re.search(pattern, text) for pattern in SPECIFIC_DATING_INTENT_PATTERNS):
        return False
    return any(phrase in text for phrase in GENERIC_DATING_INTENT_PHRASES) or bool(
        re.search(r"\b(relationship|dating|partner|someone|special)\b", text)
    )


def _candidate_as_final_point(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": candidate.get("category") or "conversation_context",
        "key": candidate.get("key"),
        "label": candidate.get("label"),
        "meaning": candidate.get("meaning"),
        "value": candidate.get("value") if isinstance(candidate.get("value"), dict) else {},
        "privacy_level": "normal",
    }


def _normalize_review_usage(raw_usage: Any, fallback_usage: Any = None) -> dict[str, bool]:
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    fallback = fallback_usage if isinstance(fallback_usage, dict) else {}
    debug_only = bool(usage.get("debug_only", fallback.get("debug_only", False)))
    return {
        "chat_context": bool(usage.get("chat_context", fallback.get("chat_context", True)))
        and not debug_only,
        "matching": bool(usage.get("matching", fallback.get("matching", False))) and not debug_only,
        "style": bool(usage.get("style", fallback.get("style", False))) and not debug_only,
        "debug_only": debug_only,
    }


def _evidence_items(value: Any) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [str(item) for item in value]
    else:
        items = []
    return [_clean_text(item, 220) for item in items if _clean_text(item, 220)]


def _dedupe_llm_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for point in points:
        identity = (str(point["category"]), str(point["key"]))
        existing = deduped.get(identity)
        if not existing or point["confidence"] > existing["confidence"]:
            deduped[identity] = point
    return list(deduped.values())


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _confidence(value: Any, *, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, confidence))


def _privacy_level(value: Any) -> str:
    level = str(value or "normal").strip().lower()
    return level if level in {"normal", "private", "sensitive"} else "normal"


def _snake_key(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")
