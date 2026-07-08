from __future__ import annotations

from typing import Any, Literal

Rating = Literal["good", "off", "bad", "harmful"]
FEEDBACK_RATINGS = {"good", "off", "bad", "harmful"}

FEEDBACK_REASONS = {
    "rating_good",
    "rating_off",
    "rating_bad",
    "rating_harmful",
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
    if rating not in FEEDBACK_RATINGS:
        raise ValueError("Feedback rating must be good, off, bad, or harmful.")

    reasons = _normalize_feedback_reasons(feedback.get("metadata", {}).get("reasons"))
    reason = str(feedback.get("reason") or "").strip().lower()
    if reason and reason not in reasons:
        reasons.insert(0, reason)
    reasons = _normalize_feedback_reasons(reasons)
    reason = reasons[0] if reasons else None

    comment = str(feedback.get("comment") or "").strip()
    metadata = feedback.get("metadata") or {}
    return {
        "conversation_id": feedback["conversation_id"],
        "user_id": feedback.get("user_id"),
        "message_index": int(feedback["message_index"]),
        "rating": rating,
        "reason": reason,
        "comment": comment[:1000] if comment else None,
        "metadata": {**metadata, "reasons": reasons},
    }


def _normalize_feedback_reasons(raw_reasons: Any) -> list[str]:
    if isinstance(raw_reasons, str):
        candidates = [raw_reasons]
    elif isinstance(raw_reasons, list):
        candidates = raw_reasons
    else:
        candidates = []

    reasons: list[str] = []
    for candidate in candidates:
        reason = str(candidate or "").strip().lower()
        if reason and reason not in FEEDBACK_REASONS:
            reason = "other"
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons[:8]
