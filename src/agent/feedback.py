from __future__ import annotations

from typing import Any, Literal

Rating = Literal["up", "down"]

FEEDBACK_REASONS = {
    "not_me",
    "wrong_memory",
    "bad_tone",
    "too_much",
    "not_helpful",
    "unsafe",
    "other",
}


def normalize_message_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    rating = str(feedback["rating"]).strip().lower()
    if rating not in {"up", "down"}:
        raise ValueError("Feedback rating must be up or down.")

    reason = str(feedback.get("reason") or "").strip().lower()
    if reason and reason not in FEEDBACK_REASONS:
        reason = "other"

    comment = str(feedback.get("comment") or "").strip()
    return {
        "conversation_id": feedback["conversation_id"],
        "user_id": feedback.get("user_id"),
        "message_index": int(feedback["message_index"]),
        "rating": rating,
        "reason": reason or None,
        "comment": comment[:1000] if comment else None,
        "metadata": feedback.get("metadata") or {},
    }
