from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ingestion.whatsapp import WhatsappMessage, WhatsappStructuredMemory

WHATSAPP_DATA_POINT_SOURCE_KIND = "whatsapp_import"
WHATSAPP_DISABLED_DATA_POINT_EXTRACTORS = {
    "inside_jokes": "reserved_for_later",
    "personality_traits": "reserved_for_later",
    "relationship_dynamics": "reserved_for_later",
}

MIN_MEANING_SCORE = 2.0


@dataclass(frozen=True)
class DataPointCandidate:
    category: str
    key: str
    label: str
    meaning: str
    value: dict[str, Any]
    evidence: list[str]
    confidence: float
    score: float


def extract_whatsapp_data_point_candidates(
    memory: WhatsappStructuredMemory,
    *,
    source_id: str,
    title: str,
) -> list[dict[str, Any]]:
    """Return rule-generated draft candidates for LLM review/debug."""
    return [
        _candidate_payload(candidate, source_id, title, memory)
        for candidate in _rule_candidates(memory, source_id)
        if _is_meaningful_candidate(candidate)
    ]


def extract_whatsapp_data_points(
    memory: WhatsappStructuredMemory,
    *,
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
) -> list[dict[str, Any]]:
    return _dedupe_points(
        [
            _point_from_candidate(candidate, user_id, source_id, import_id, title, memory)
            for candidate in _rule_candidates(memory, source_id)
            if _is_meaningful_candidate(candidate)
        ]
    )


def _rule_candidates(
    memory: WhatsappStructuredMemory,
    source_id: str,
) -> list[DataPointCandidate]:
    candidates: list[DataPointCandidate] = []
    candidates.extend(_meaningful_topic_candidates(memory, source_id))
    recent_candidate = _recent_coordination_candidate(memory, source_id)
    if recent_candidate:
        candidates.append(recent_candidate)
    candidates.extend(_tone_trait_candidates(memory, source_id))
    return candidates


def _tone_trait_candidates(
    memory: WhatsappStructuredMemory,
    source_id: str,
) -> list[DataPointCandidate]:
    candidates = []
    for profile in memory.style_profiles[:4]:
        traits = _tone_traits(profile.summary)
        if not traits:
            continue
        sender_key = _source_key(profile.sender)
        score = _tone_meaning_score(profile.summary, profile.sample_messages)
        candidates.append(
            DataPointCandidate(
                category="whatsapp_tone_traits",
                key=f"{_source_key(source_id)}_{sender_key}_tone",
                value={
                    "kind": "whatsapp_tone_traits",
                    "sender": profile.sender,
                    "traits": traits,
                    "meaning": f"Useful for adapting replies toward {profile.sender}'s rhythm without impersonating them.",
                    "summary": profile.summary,
                    "sample_messages": profile.sample_messages[:3],
                    "role": profile.metadata.get("role"),
                },
                label=f"{profile.sender}'s WhatsApp style is {', '.join(traits[:4])}",
                meaning=f"Useful for adapting replies toward {profile.sender}'s rhythm without impersonating them.",
                confidence=_tone_confidence(profile.summary, profile.sample_messages),
                evidence=[
                    f"{profile.sender}: {sample}"
                    for sample in profile.sample_messages[:3]
                    if sample.strip()
                ],
                score=score,
            )
        )
    return candidates


TOPIC_DOMAINS: dict[str, dict[str, Any]] = {
    "meeting_coordination": {
        "label": "coordinates meeting/place details",
        "meaning": "Useful when the user asks about practical plans, last meetup context, or where/when something was decided.",
        "terms": {
            "location",
            "kidhar",
            "where",
            "wahi",
            "there",
            "gate",
            "rukna",
            "wait",
            "chalega",
            "bje",
            "around",
            "time",
            "late",
            "meet",
            "meeting",
            "call",
            "voice",
        },
    },
    "casual_plan": {
        "label": "makes casual plans",
        "meaning": "Useful for remembering the actual activity or plan being discussed rather than only raw keywords.",
        "terms": {
            "plan",
            "coffee",
            "walk",
            "movie",
            "food",
            "dinner",
            "lunch",
            "date",
            "outing",
            "first",
            "then",
        },
    },
    "relationship_intent": {
        "label": "talks about relationship/dating intent",
        "meaning": "Useful for dating-context replies and matching only when the signal is explicit enough.",
        "terms": {
            "relationship",
            "dating",
            "partner",
            "special",
            "someone",
            "girl",
            "boy",
            "shaadi",
            "love",
        },
    },
    "music_entertainment": {
        "label": "talks about music or entertainment",
        "meaning": "Useful for playful conversation hooks when this appears repeatedly, not as a one-off filler word.",
        "terms": {"music", "song", "songs", "playlist", "movie", "scene", "actor"},
    },
}


def _meaningful_topic_candidates(
    memory: WhatsappStructuredMemory,
    source_id: str,
) -> list[DataPointCandidate]:
    candidates: list[DataPointCandidate] = []
    messages = [message for message in memory.messages if message.content.strip()]
    for domain_key, domain in TOPIC_DOMAINS.items():
        matched_messages = _messages_matching_terms(messages, domain["terms"])
        if len(matched_messages) < 2:
            continue
        matched_terms = _matched_terms(matched_messages, domain["terms"])
        score = _meaning_score(
            evidence_count=len(matched_messages),
            term_count=len(matched_terms),
            has_action=any(_has_action_language(message.content) for message in matched_messages),
        )
        if domain_key == "music_entertainment" and len(matched_messages) < 4:
            score -= 1.0
        label_detail = _topic_label_detail(domain_key, matched_terms)
        candidates.append(
            DataPointCandidate(
                category="whatsapp_recurring_topics",
                key=f"{_source_key(source_id)}_{domain_key}",
                label=f"WhatsApp chat {domain['label']}: {label_detail}",
                meaning=str(domain["meaning"]),
                value={
                    "kind": "whatsapp_recurring_topic",
                    "topic_key": domain_key,
                    "matched_terms": matched_terms[:10],
                    "message_count": len(matched_messages),
                },
                evidence=[_message_preview(message) for message in matched_messages[-5:]],
                confidence=_confidence_from_score(score, base=0.55),
                score=score,
            )
        )
    return candidates


def _recent_coordination_candidate(
    memory: WhatsappStructuredMemory,
    source_id: str,
) -> DataPointCandidate | None:
    recent_messages = [message for message in memory.messages[-10:] if message.content.strip()]
    if len(recent_messages) < 2:
        return None
    action_messages = [
        message
        for message in recent_messages
        if _has_action_language(message.content)
        or _message_matches_terms(message, TOPIC_DOMAINS["meeting_coordination"]["terms"])
        or _message_matches_terms(message, TOPIC_DOMAINS["casual_plan"]["terms"])
    ]
    if len(action_messages) < 2:
        return None

    recent_terms = (
        TOPIC_DOMAINS["meeting_coordination"]["terms"] | TOPIC_DOMAINS["casual_plan"]["terms"]
    )
    matched_terms = _matched_terms(action_messages, recent_terms)
    score = _meaning_score(
        evidence_count=len(action_messages),
        term_count=len(matched_terms),
        has_action=True,
        recency_bonus=0.7,
    )
    label = _recent_event_label(action_messages, matched_terms)
    return DataPointCandidate(
        category="whatsapp_recent_events",
        key=f"{_source_key(source_id)}_recent_coordination",
        label=label,
        meaning="Useful when the user asks what was happening recently or what the last concrete plan/context was.",
        value={
            "kind": "whatsapp_recent_coordination",
            "recent_terms": matched_terms[:10],
            "message_count": len(action_messages),
            "message_previews": [_message_preview(message) for message in action_messages[-5:]],
        },
        evidence=[_message_preview(message) for message in action_messages[-5:]],
        confidence=_confidence_from_score(score, base=0.54),
        score=score,
    )


def _candidate_payload(
    candidate: DataPointCandidate,
    source_id: str,
    title: str,
    memory: WhatsappStructuredMemory,
) -> dict[str, Any]:
    return {
        "source": "rules",
        "source_kind": WHATSAPP_DATA_POINT_SOURCE_KIND,
        "source_id": source_id,
        "title": title,
        "selected_sender": memory.metadata.get("selected_sender"),
        "category": candidate.category,
        "key": candidate.key,
        "label": candidate.label,
        "meaning": candidate.meaning,
        "value": candidate.value,
        "confidence": candidate.confidence,
        "formation_score": round(candidate.score, 2),
        "evidence": candidate.evidence[:5],
        "usage": {
            "chat_context": True,
            "matching": False,
            "style": candidate.category == "whatsapp_tone_traits",
            "debug_only": False,
        },
    }


def _point_from_candidate(
    candidate: DataPointCandidate,
    user_id: str,
    source_id: str,
    import_id: str,
    title: str,
    memory: WhatsappStructuredMemory,
) -> dict[str, Any]:
    return _point(
        user_id=user_id,
        category=candidate.category,
        key=candidate.key,
        value={
            **candidate.value,
            "title": title,
            "selected_sender": memory.metadata.get("selected_sender"),
            "meaning": candidate.meaning,
            "rule_candidate": _candidate_payload(candidate, source_id, title, memory),
            "formation_score": round(candidate.score, 2),
        },
        label=candidate.label,
        confidence=candidate.confidence,
        source_id=source_id,
        import_id=import_id,
        evidence_text=" | ".join(candidate.evidence),
    )


def _is_meaningful_candidate(candidate: DataPointCandidate) -> bool:
    if candidate.score < MIN_MEANING_SCORE:
        return False
    if not candidate.evidence:
        return False
    return bool(candidate.label and candidate.meaning)


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


def _messages_matching_terms(
    messages: list[WhatsappMessage],
    terms: set[str],
) -> list[WhatsappMessage]:
    return [message for message in messages if _message_matches_terms(message, terms)]


def _message_matches_terms(message: WhatsappMessage, terms: set[str]) -> bool:
    message_terms = set(_tokens(message.content))
    return bool(message_terms & terms)


def _matched_terms(messages: list[WhatsappMessage], terms: set[str]) -> list[str]:
    counts: Counter[str] = Counter()
    for message in messages:
        for token in _tokens(message.content):
            if token in terms:
                counts[token] += 1
    return [term for term, _ in counts.most_common(10)]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower(), flags=re.UNICODE)


def _has_action_language(text: str) -> bool:
    action_terms = {
        "aa",
        "aaya",
        "call",
        "chalega",
        "coming",
        "first",
        "ja",
        "kar",
        "late",
        "meet",
        "plan",
        "reach",
        "rukna",
        "then",
        "wait",
        "walk",
        "will",
    }
    return bool(set(_tokens(text)) & action_terms)


def _meaning_score(
    *,
    evidence_count: int,
    term_count: int,
    has_action: bool,
    recency_bonus: float = 0.0,
) -> float:
    score = min(2.0, evidence_count * 0.45)
    score += min(1.2, term_count * 0.25)
    if has_action:
        score += 0.8
    score += recency_bonus
    return score


def _confidence_from_score(score: float, *, base: float) -> float:
    return max(0.45, min(0.88, base + score * 0.07))


def _topic_label_detail(domain_key: str, matched_terms: list[str]) -> str:
    if domain_key == "meeting_coordination":
        return _join_terms(_prefer_terms(matched_terms, ["location", "wahi", "rukna", "call", "time"]))
    if domain_key == "casual_plan":
        return _join_terms(_prefer_terms(matched_terms, ["coffee", "walk", "plan", "movie"]))
    if domain_key == "relationship_intent":
        return _join_terms(_prefer_terms(matched_terms, ["relationship", "dating", "partner", "special"]))
    return _join_terms(matched_terms[:4])


def _recent_event_label(messages: list[WhatsappMessage], terms: list[str]) -> str:
    preferred = _prefer_terms(terms, ["coffee", "walk", "location", "call", "wahi", "rukna", "plan"])
    if preferred:
        return f"Recent WhatsApp context involved { _join_terms(preferred) }"
    return f"Recent WhatsApp context: {_truncate(_message_preview(messages[-1]), 90)}"


def _prefer_terms(terms: list[str], preferred: list[str]) -> list[str]:
    ordered = [term for term in preferred if term in terms]
    ordered.extend(term for term in terms if term not in ordered)
    return ordered[:4]


def _join_terms(terms: list[str]) -> str:
    if not terms:
        return "concrete context"
    if len(terms) == 1:
        return terms[0]
    return ", ".join(terms[:-1]) + f" and {terms[-1]}"


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


def _tone_confidence(summary: dict[str, Any], samples: list[str]) -> float:
    sample_count = len([sample for sample in samples if sample.strip()])
    average_words = _float(summary.get("average_words"))
    confidence = 0.56 + min(0.16, sample_count * 0.04)
    if average_words:
        confidence += 0.06
    if summary.get("frequent_terms") or summary.get("topic_terms"):
        confidence += 0.04
    return max(0.5, min(0.82, confidence))


def _tone_meaning_score(summary: dict[str, Any], samples: list[str]) -> float:
    score = min(1.5, len([sample for sample in samples if sample.strip()]) * 0.35)
    if _float(summary.get("average_words")):
        score += 0.5
    if summary.get("frequent_terms") or summary.get("topic_terms"):
        score += 0.4
    if _percentage(summary.get("short_message_share")) >= 60:
        score += 0.4
    if _percentage(summary.get("question_share")) >= 20:
        score += 0.3
    return score


def _dedupe_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for point in points:
        identity = (str(point.get("category") or ""), str(point.get("key") or ""))
        existing = deduped.get(identity)
        if not existing or float(point.get("confidence") or 0) > float(
            existing.get("confidence") or 0
        ):
            deduped[identity] = point
    return sorted(
        deduped.values(),
        key=lambda point: (
            str(point.get("category") or ""),
            -float(point.get("confidence") or 0),
            str(point.get("key") or ""),
        ),
    )


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
