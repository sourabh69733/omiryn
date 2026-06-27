from __future__ import annotations

import logging
import os
import re
from typing import Any

from agent.data_points import normalize_data_point
from agent.providers import extract_llm_data_point_candidates
from ingestion.whatsapp import WhatsappStructuredMemory
from storage import upsert_profile_fact

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
}


def data_point_extractor_mode() -> str:
    mode = os.getenv("DATA_POINT_EXTRACTOR", "rules").strip().lower()
    if mode in {"llm", "hybrid", "rules"}:
        return mode
    return "rules"


def should_run_llm_data_point_extraction() -> bool:
    return data_point_extractor_mode() in {"llm", "hybrid"}


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


def normalize_llm_data_points(
    raw: dict[str, Any],
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
) -> list[dict[str, Any]]:
    raw_points = raw.get("data_points") or raw.get("points")
    if not isinstance(raw_points, list):
        return []

    points: list[dict[str, Any]] = []
    for index, raw_point in enumerate(raw_points[:LLM_MAX_POINTS]):
        if not isinstance(raw_point, dict):
            continue
        point = _normalize_llm_data_point(raw_point, user_id, source_id, import_id, title, index)
        if point:
            points.append(point)
    return _dedupe_llm_points(points)


def _normalize_llm_data_point(
    raw: dict[str, Any],
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
    index: int,
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
        "source_kind": "whatsapp_import",
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
