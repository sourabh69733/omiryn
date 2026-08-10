from __future__ import annotations

from typing import Any


DATA_POINT_FEEDBACK_RATINGS = {"agree", "disagree"}


def normalize_data_point_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    rating = str(feedback["rating"]).strip().lower()
    if rating not in DATA_POINT_FEEDBACK_RATINGS:
        raise ValueError("Data point feedback rating must be agree or disagree.")

    reason = str(feedback.get("reason") or "").strip().lower().replace(" ", "_")[:80]
    comment = str(feedback.get("comment") or "").strip()[:1000]
    return {
        "user_id": str(feedback["user_id"]),
        "profile_fact_id": str(feedback["profile_fact_id"]),
        "rating": rating,
        "reason": reason or None,
        "comment": comment or None,
        "metadata": feedback.get("metadata") or {},
    }
