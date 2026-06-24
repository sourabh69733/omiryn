from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable

from ingestion.whatsapp import WhatsappMessage, WhatsappStructuredMemory

WHATSAPP_DATA_POINT_SOURCE_KIND = "whatsapp_import"
WHATSAPP_DISABLED_DATA_POINT_EXTRACTORS = {
    "inside_jokes": "reserved_for_later",
    "personality_traits": "reserved_for_later",
    "relationship_dynamics": "reserved_for_later",
}

Extractor = Callable[
    [WhatsappStructuredMemory, str, str, str, str],
    list[dict[str, Any]],
]


def extract_whatsapp_data_points(
    memory: WhatsappStructuredMemory,
    *,
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for extractor in WHATSAPP_DATA_POINT_EXTRACTORS.values():
        points.extend(extractor(memory, user_id, source_id, import_id, title))
    return points


def _topic_points(
    memory: WhatsappStructuredMemory,
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
) -> list[dict[str, Any]]:
    terms = _top_terms(memory)
    if not terms:
        return []
    return [
        _point(
            user_id=user_id,
            category="whatsapp_topics",
            key=f"{_source_key(source_id)}_topics",
            value={
                "kind": "whatsapp_topics",
                "topics": terms,
                "title": title,
                "selected_sender": memory.metadata.get("selected_sender"),
            },
            label=f"WhatsApp topics include {', '.join(terms[:5])}",
            confidence=0.72,
            source_id=source_id,
            import_id=import_id,
            evidence_text=f"Topic terms from parsed WhatsApp import: {', '.join(terms)}",
        )
    ]


def _recent_event_points(
    memory: WhatsappStructuredMemory,
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
) -> list[dict[str, Any]]:
    recent_messages = memory.messages[-8:]
    if not recent_messages:
        return []
    previews = [_message_preview(message) for message in recent_messages if message.content.strip()]
    terms = _message_terms(recent_messages)
    label_detail = ", ".join(terms[:5]) if terms else _truncate(previews[-1], 80)
    return [
        _point(
            user_id=user_id,
            category="whatsapp_recent_events",
            key=f"{_source_key(source_id)}_recent_events",
            value={
                "kind": "whatsapp_recent_events",
                "title": title,
                "selected_sender": memory.metadata.get("selected_sender"),
                "recent_terms": terms,
                "message_previews": previews[-5:],
            },
            label=f"Recent WhatsApp context mentions {label_detail}",
            confidence=0.68,
            source_id=source_id,
            import_id=import_id,
            evidence_text="Recent parsed WhatsApp messages: " + " | ".join(previews[-5:]),
        )
    ]


def _tone_trait_points(
    memory: WhatsappStructuredMemory,
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
) -> list[dict[str, Any]]:
    points = []
    for profile in memory.style_profiles[:4]:
        traits = _tone_traits(profile.summary)
        if not traits:
            continue
        sender_key = _source_key(profile.sender)
        points.append(
            _point(
                user_id=user_id,
                category="whatsapp_tone_traits",
                key=f"{_source_key(source_id)}_{sender_key}_tone",
                value={
                    "kind": "whatsapp_tone_traits",
                    "title": title,
                    "sender": profile.sender,
                    "traits": traits,
                    "summary": profile.summary,
                    "sample_messages": profile.sample_messages[:3],
                    "role": profile.metadata.get("role"),
                },
                label=f"{profile.sender}'s WhatsApp tone is {', '.join(traits[:4])}",
                confidence=0.7,
                source_id=source_id,
                import_id=import_id,
                evidence_text="Style signals from parsed WhatsApp import: "
                + "; ".join(profile.sample_messages[:3]),
            )
        )
    return points


WHATSAPP_DATA_POINT_EXTRACTORS: dict[str, Extractor] = {
    "topics": _topic_points,
    "recent_events": _recent_event_points,
    "tone_traits": _tone_trait_points,
}


def _point(
    *,
    user_id: str,
    category: str,
    key: str,
    value: dict[str, Any],
    label: str,
    confidence: float,
    source_id: str,
    import_id: str,
    evidence_text: str,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "category": category,
        "key": key,
        "value": {**value, "context_source_id": source_id, "import_id": import_id},
        "label": label,
        "confidence": confidence,
        "source_kind": WHATSAPP_DATA_POINT_SOURCE_KIND,
        "source_id": source_id,
        "evidence": [
            {
                "context_source_id": source_id,
                "import_id": import_id,
                "text": evidence_text[:320],
            }
        ],
        "status": "active",
        "visibility": "internal",
        "used_for_matching": False,
        "used_for_chat_context": True,
    }


def _top_terms(memory: WhatsappStructuredMemory) -> list[str]:
    counts: Counter[str] = Counter()
    for chunk in memory.chunks:
        for term in chunk.terms:
            counts[_clean_term(term)] += 2
    for profile in memory.style_profiles:
        summary = profile.summary
        for term in summary.get("topic_terms") or summary.get("frequent_terms") or []:
            counts[_clean_term(str(term))] += 1
    return [term for term, _ in counts.most_common(10) if term]


def _message_terms(messages: list[WhatsappMessage]) -> list[str]:
    stopwords = {
        "about",
        "also",
        "and",
        "but",
        "for",
        "hai",
        "just",
        "kar",
        "kya",
        "mai",
        "mein",
        "that",
        "the",
        "this",
        "you",
    }
    counts = Counter(
        token
        for message in messages
        for token in re.findall(r"[\w']+", message.content.lower(), flags=re.UNICODE)
        if len(token) >= 3 and token not in stopwords
    )
    return [term for term, _ in counts.most_common(8)]


def _tone_traits(summary: dict[str, Any]) -> list[str]:
    traits: list[str] = []
    average_words = _float(summary.get("average_words"))
    if average_words and average_words <= 4:
        traits.append("brief")
    elif average_words and average_words >= 12:
        traits.append("detailed")

    short_share = _percentage(summary.get("short_message_share"))
    question_share = _percentage(summary.get("question_share"))
    exclamation_share = _percentage(summary.get("exclamation_share"))
    emoji_share = _percentage(summary.get("emoji_like_share"))
    lowercase_share = _percentage(summary.get("lowercase_opening_share"))

    if short_share >= 60:
        traits.append("short-message heavy")
    if question_share >= 25:
        traits.append("question-led")
    if exclamation_share >= 20:
        traits.append("expressive")
    if emoji_share >= 20:
        traits.append("emoji/non-ASCII friendly")
    if lowercase_share >= 50:
        traits.append("casual lowercase")

    return traits or ["casual direct"]


def _message_preview(message: WhatsappMessage) -> str:
    timestamp = f"{message.timestamp_text} " if message.timestamp_text else ""
    return _truncate(f"{timestamp}{message.sender}: {' '.join(message.content.split())}", 180)


def _source_key(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")[:80]


def _clean_term(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _percentage(value: Any) -> float:
    text = str(value or "").strip().removesuffix("%")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."
