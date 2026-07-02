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


def context_query_intent(user_text: str) -> ContextQueryIntent:
    normalized = normalized_memory_text(user_text)
    query_terms = memory_terms(user_text)
    labels: list[str] = []
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

    prefer_structured = bool({"whatsapp", "recent", "style", "topics"} & set(labels)) and (
        "whatsapp" in labels
        or "style" in labels
        or ("recent" in labels and any(term in query_terms for term in WHATSAPP_QUERY_TERMS))
        or ("topics" in labels and any(term in query_terms for term in WHATSAPP_QUERY_TERMS))
    )
    return ContextQueryIntent(tuple(labels), prefer_structured)
