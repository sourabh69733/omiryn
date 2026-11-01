"""Saves how-to-talk requests the moment the request checker finds one, in the turn itself.

Before this, a request ("stop asking that", "english?") held in the same chat through the checker,
and in other chats only once the background run saved it minutes later, if it did. Now the checker
names the requests it read in the user's recent messages, and code saves each as a procedural
memory with that message as evidence. The background run still sees it and may refine or replace it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from agent.context_engine.policy.freshness import _normalize, _word_overlap
from agent.shared.clock import utc_now
from agent.shared.memory_models import MemoryKind, MemoryPurpose

logger = logging.getLogger(__name__)

EXTRACTOR = "request_check"
# Two requests sharing this much of their words are the same request in other words.
_SAME_REQUEST_OVERLAP = 0.6
_KEY_WORDS = 6


def save_talk_requests(
    user_id: str,
    conversation_id: str,
    history: list[dict[str, Any]],
    user_text: str,
    requests: list[tuple[str, str]],
    *,
    now: datetime | None = None,
) -> list[str]:
    """Create one procedural memory per new request; returns the ids. Never raises."""
    if not requests or not user_id or not conversation_id:
        return []
    try:
        return _save(user_id, conversation_id, history, user_text, requests, now or utc_now())
    except Exception:
        logger.exception("agent.talk_requests.save_failed")
        return []


def _save(user_id: str, conversation_id: str, history: list[dict[str, Any]], user_text: str, requests: list[tuple[str, str]], now: datetime) -> list[str]:
    from storage import create_agent_memory, get_conversation, list_agent_memories

    conversation = get_conversation(conversation_id, user_id)
    if not conversation or conversation.get("temporary"):
        return []
    existing = [
        _normalize(str(memory.get("statement") or memory.get("value") or ""))
        for memory in list_agent_memories(user_id)
        if memory.get("kind") == MemoryKind.PROCEDURAL.value and memory.get("status", "active") == "active"
    ]
    saved: list[str] = []
    for request, source in requests:
        normalized = _normalize(request)
        if not normalized or any(_word_overlap(normalized, other) >= _SAME_REQUEST_OVERLAP for other in existing if other):
            continue
        index = _message_index(history, user_text, source)
        if index is None:
            continue
        memory = create_agent_memory(
            {
                "user_id": user_id,
                "kind": MemoryKind.PROCEDURAL.value,
                "purposes": [MemoryPurpose.PERSONALIZATION.value],
                "key": "how_to_talk." + "_".join(normalized.split()[:_KEY_WORDS]),
                "value": request,
                "statement": request,
                "confidence": 0.8,
                "importance": 0.7,
                "evidence": [{"conversation_id": conversation_id, "message_index": index, "exact_quote": source[:300], "observed_at": now.isoformat()}],
                "extractor": EXTRACTOR,
            }
        )
        existing.append(normalized)
        saved.append(str(memory["id"]))
    return saved


def _message_index(history: list[dict[str, Any]], user_text: str, source: str) -> int | None:
    """Where the quoted user message sits in the stored chat: the current message comes after the history."""
    for index in range(len(history) - 1, -1, -1):
        message = history[index]
        if message.get("role") == "user" and str(message.get("content") or "").strip()[: len(source)] == source:
            return index
    if user_text and user_text.strip()[: len(source)] == source:
        return len(history)
    return None


__all__ = ["EXTRACTOR", "save_talk_requests"]
