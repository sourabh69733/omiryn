"""Turns a reason the user keeps giving for bad replies into a lasting how-to-talk memory.

The last few rated replies already reach the next reply as examples, but they fall out after a
handful of ratings or 30 days. When the same reason is picked on several replies, it is saved as
a procedural memory, which every reply sees. The memory states what the user did (rated replies
down for a reason), with the rated replies as proof. Undoing ratings below the threshold removes it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from agent.shared.clock import utc_now
from agent.shared.timeline import parse_time
from storage import (
    create_agent_memory,
    delete_agent_memory,
    get_conversation,
    list_agent_memories,
    list_agent_message_feedback,
)

# Same reason on this many replies within the window makes it lasting.
RATINGS_FOR_MEMORY = 2
WINDOW_DAYS = 30
EXTRACTOR = "reply_ratings"
_KEY_PREFIX = "reply_rating:"
# What each reason in the Bad reply menu says about the reply.
_REASON_WORDS = {
    "too_much": "being too long",
    "bad_tone": "having the wrong tone",
    "wrong_memory": "getting facts about them wrong",
    "not_helpful": "not being helpful",
}
_QUOTE_CHARS = 160


def sync_rating_memories(user_id: str) -> dict[str, list[str]]:
    """Create or remove rating memories to match the user's recent bad ratings."""
    rated = _recent_bad_ratings(user_id)
    existing = {
        str(memory["key"]): memory
        for memory in list_agent_memories(user_id)
        if memory.get("extractor") == EXTRACTOR and memory.get("status") == "active"
    }
    changed: dict[str, list[str]] = {"added": [], "removed": []}
    for reason, words in _REASON_WORDS.items():
        key = _KEY_PREFIX + reason
        ratings = rated.get(reason, [])
        if len(ratings) >= RATINGS_FOR_MEMORY and key not in existing:
            evidence = _evidence(user_id, ratings)
            if len(evidence) >= RATINGS_FOR_MEMORY:
                create_agent_memory(_memory(user_id, key, reason, words, evidence))
                changed["added"].append(reason)
        elif len(ratings) < RATINGS_FOR_MEMORY and key in existing:
            delete_agent_memory(existing[key]["id"], user_id)
            changed["removed"].append(reason)
    return changed


def _recent_bad_ratings(user_id: str) -> dict[str, list[dict[str, Any]]]:
    cutoff = utc_now() - timedelta(days=WINDOW_DAYS)
    by_reason: dict[str, list[dict[str, Any]]] = {}
    for item in list_agent_message_feedback(user_id=user_id):
        created = parse_time(item.get("created_at"))
        if item.get("rating") == "good" or (created is not None and created < cutoff):
            continue
        for reason in (item.get("metadata") or {}).get("reasons") or []:
            if reason in _REASON_WORDS:
                by_reason.setdefault(reason, []).append(item)
    return by_reason


def _evidence(user_id: str, ratings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chats: dict[str, list[dict[str, Any]]] = {}
    evidence = []
    for item in ratings:
        conversation_id = str(item["conversation_id"])
        if conversation_id not in chats:
            chats[conversation_id] = list((get_conversation(conversation_id, user_id) or {}).get("messages") or [])
        messages = chats[conversation_id]
        index = int(item["message_index"])
        reply = str(messages[index].get("content") or "") if 0 <= index < len(messages) else ""
        if not reply.strip():
            continue
        evidence.append(
            {
                "conversation_id": conversation_id,
                "message_index": index,
                "exact_quote": " ".join(reply.replace("<next_message>", " ").split())[:_QUOTE_CHARS],
                "observed_at": item["created_at"],
            }
        )
    return evidence


def _memory(user_id: str, key: str, reason: str, words: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "kind": "procedural",
        "purposes": ["personalization"],
        "key": key,
        "value": {"rated_replies_down_for": words, "times": len(evidence)},
        "statement": f"Rated the companion's replies down for {words}.",
        "confidence": 0.9,
        "importance": 0.7,
        "evidence": evidence,
        "extractor": EXTRACTOR,
    }


__all__ = ["RATINGS_FOR_MEMORY", "sync_rating_memories"]
