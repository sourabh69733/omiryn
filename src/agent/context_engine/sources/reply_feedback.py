"""Replies the user rated, so the next reply learns from them right away."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from agent.shared.clock import utc_now
from agent.shared.timeline import parse_time
from storage import get_conversation, list_agent_message_feedback

REPLY_FEEDBACK_SOURCE_TYPE = "reply_feedback"
# Recent ratings shown on every reply, newest first; older ones have done their job.
REPLY_FEEDBACK_WINDOW_DAYS = 30
REPLY_FEEDBACK_DISLIKED = 3
REPLY_FEEDBACK_LIKED = 2
_FEEDBACK_REASON_WORDS = {
    "too_much": "too much",
    "bad_tone": "the tone felt off",
    "not_me": "not like them",
    "wrong_memory": "got something about them wrong",
    "not_helpful": "not helpful",
    "unsafe": "felt unsafe",
}


def reply_feedback_sources(user_id: str | None) -> list[dict[str, Any]]:
    """Replies the user rated, so the next reply learns from them right away."""
    if not user_id:
        return []
    cutoff = utc_now() - timedelta(days=REPLY_FEEDBACK_WINDOW_DAYS)
    disliked: list[str] = []
    liked: list[str] = []
    chats: dict[str, list[dict[str, Any]]] = {}
    for item in list_agent_message_feedback(user_id=user_id):  # newest first
        created = parse_time(item.get("created_at"))
        if created is not None and created < cutoff:
            break
        bucket = liked if item["rating"] == "good" else disliked
        if len(bucket) >= (REPLY_FEEDBACK_LIKED if bucket is liked else REPLY_FEEDBACK_DISLIKED):
            continue
        conversation_id = str(item["conversation_id"])
        if conversation_id not in chats:
            chats[conversation_id] = list((get_conversation(conversation_id, user_id) or {}).get("messages") or [])
        messages = chats[conversation_id]
        index = int(item["message_index"])
        reply = str(messages[index].get("content") or "") if 0 <= index < len(messages) else ""
        if not reply.strip():
            continue
        reasons = [
            _FEEDBACK_REASON_WORDS[reason]
            for reason in (item.get("metadata") or {}).get("reasons") or []
            if reason in _FEEDBACK_REASON_WORDS
        ]
        note = "; ".join(filter(None, [", ".join(reasons), str(item.get("comment") or "").strip()[:160]]))
        quoted = " ".join(reply.replace("<next_message>", " ").split())[:160]
        bucket.append(f"- \"{quoted}\"" + (f" ({note})" if note and bucket is disliked else ""))
    if not disliked and not liked:
        return []
    lines = ["Replies of yours they rated. Learn the pattern; never repeat these lines or mention the ratings."]
    if disliked:
        lines += ["They disliked:", *disliked]
    if liked:
        lines += ["They liked:", *liked]
    return [
        {
            "source_type": REPLY_FEEDBACK_SOURCE_TYPE,
            "title": "Replies they rated",
            "content": "\n".join(lines),
            "metadata": {"disliked": len(disliked), "liked": len(liked)},
        }
    ]


__all__ = ["REPLY_FEEDBACK_SOURCE_TYPE", "reply_feedback_sources"]
