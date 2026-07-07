from __future__ import annotations

from agent.context_engine.models import ContextQueryIntent
from agent.context_engine.utils import memory_terms, normalized_memory_text

RECENCY_QUERY_TERMS = {"last", "latest", "recent", "previous", "pichli", "pehle", "before"}
WHATSAPP_QUERY_TERMS = {
    "whatsapp",
    "message",
    "messages",
    "msg",
    "chat",
    "convo",
    "conversation",
    "sender",
    "sent",
    "reply",
    "replies",
}
STYLE_QUERY_TERMS = {"style", "tone", "talk", "talking", "text", "texts", "way", "baat"}
TOPIC_QUERY_TERMS = {"topic", "topics", "about", "baate", "baat"}
WHATSAPP_QUERY_PHRASES = {
    "hum kya",
    "kaise baat",
    "kaise text",
    "kis style",
    "kis bare",
    "kya baat",
    "kya baate",
    "last convo",
    "last message",
    "pichli baat",
    "uploaded chat",
    "whatsapp chat",
}
LOW_INFORMATION_TERMS = {"hmm", "hm", "ok", "okay", "yeah", "yes", "no", "haan", "ha", "nhi", "nah"}
ADULT_FLIRTY_TERMS = {"sexy", "hot", "adult", "intimate", "flirt", "flirty", "romantic"}
STORY_TERMS = {"story", "scene", "continue", "example", "imagine", "roleplay"}
PROFILE_RECALL_PHRASES = {"what do you know", "about me", "know me", "meri profile"}


def context_query_intent(user_text: str) -> ContextQueryIntent:
    normalized = normalized_memory_text(user_text)
    query_terms = memory_terms(user_text)
    labels: list[str] = []
    entities = _named_entities(user_text)
    is_low_information = normalized in LOW_INFORMATION_TERMS or (
        len(normalized.split()) <= 2 and not query_terms
    )
    if any(term in query_terms for term in WHATSAPP_QUERY_TERMS) or any(
        phrase in normalized for phrase in WHATSAPP_QUERY_PHRASES
    ):
        labels.append("whatsapp")
    if query_terms & RECENCY_QUERY_TERMS:
        labels.append("recent")
    if query_terms & STYLE_QUERY_TERMS or any(
        phrase in normalized for phrase in {"kaise baat", "kaise text", "kis style"}
    ):
        labels.append("style")
    if query_terms & TOPIC_QUERY_TERMS:
        labels.append("topics")
    if any(phrase in normalized for phrase in PROFILE_RECALL_PHRASES):
        labels.append("profile_recall")
    if query_terms & ADULT_FLIRTY_TERMS:
        labels.append("adult_flirty")
    if query_terms & STORY_TERMS:
        labels.append("story_or_long_reply")
    if is_low_information:
        labels.append("low_information")

    prefer_structured = bool({"whatsapp", "recent", "style", "topics"} & set(labels)) and (
        "whatsapp" in labels
        or "style" in labels
        or ("recent" in labels and any(term in query_terms for term in WHATSAPP_QUERY_TERMS))
        or ("topics" in labels and any(term in query_terms for term in WHATSAPP_QUERY_TERMS))
    )
    confidence = min(0.95, 0.25 + (len(labels) * 0.18) + (len(entities) * 0.08))
    return ContextQueryIntent(
        tuple(labels),
        prefer_structured,
        confidence=confidence if labels else 0.15,
        entities=tuple(entities),
        is_low_information=is_low_information,
    )


def _named_entities(text: str) -> list[str]:
    entities: list[str] = []
    for token in text.replace("?", " ").replace(",", " ").split():
        cleaned = token.strip("'\"“”‘’():;")
        if len(cleaned) >= 3 and cleaned[:1].isupper() and cleaned[1:].islower():
            entities.append(cleaned)
    return entities[:4]
