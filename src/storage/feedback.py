from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from .database import ENGINE
from .schema import feedback_submissions
from .utils import _isoformat_utc


def save_feedback_submission(submission: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": submission.get("id") or str(uuid4()),
        "user_id": str(submission["user_id"]),
        "email": _clean_text(submission.get("email"), 240),
        "category": _clean_text(submission.get("category"), 40) or "feedback",
        "message": _clean_text(submission.get("message"), 4000) or "",
        "allow_contact": bool(submission.get("allow_contact")),
        "status": _clean_text(submission.get("status"), 40) or "open",
        "metadata_json": submission.get("metadata") if isinstance(submission.get("metadata"), dict) else {},
    }
    with ENGINE.begin() as connection:
        connection.execute(feedback_submissions.insert().values(**payload))
        row = connection.execute(
            select(feedback_submissions).where(feedback_submissions.c.id == payload["id"])
        ).mappings().first()
    return _feedback_submission_from_row(row)


def list_user_feedback_submissions(user_id: str) -> list[dict[str, Any]]:
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(feedback_submissions)
            .where(feedback_submissions.c.user_id == user_id)
            .order_by(feedback_submissions.c.created_at.desc())
        ).mappings().all()
    return [_feedback_submission_from_row(row) for row in rows]


def _clean_text(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def _feedback_submission_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "email": row["email"],
        "category": row["category"],
        "message": row["message"],
        "allow_contact": row["allow_contact"],
        "status": row["status"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }
