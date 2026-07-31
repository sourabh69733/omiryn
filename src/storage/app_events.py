from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from .database import ENGINE
from .schema import app_events
from .utils import _isoformat_utc


def save_app_events(user_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads = [_app_event_payload(user_id, event) for event in events]
    if not payloads:
        return []
    with ENGINE.begin() as connection:
        connection.execute(app_events.insert().values(payloads))
        rows = connection.execute(
            select(app_events)
            .where(app_events.c.id.in_([payload["id"] for payload in payloads]))
            .order_by(app_events.c.created_at.asc())
        ).mappings().all()
    return [_app_event_from_row(row) for row in rows]


def list_user_app_events(user_id: str) -> list[dict[str, Any]]:
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(app_events)
            .where(app_events.c.user_id == user_id)
            .order_by(app_events.c.created_at.asc())
        ).mappings().all()
    return [_app_event_from_row(row) for row in rows]


def count_user_app_events_since(user_id: str, event_name: str, since: Any) -> int:
    with ENGINE.begin() as connection:
        return int(
            connection.execute(
                select(func.count())
                .select_from(app_events)
                .where(app_events.c.user_id == user_id)
                .where(app_events.c.event_name == event_name)
                .where(app_events.c.created_at >= since)
            ).scalar_one()
        )


def user_app_event_window_stats(user_id: str, event_name: str, since: Any) -> dict[str, Any]:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(func.count(), func.min(app_events.c.created_at))
            .select_from(app_events)
            .where(app_events.c.user_id == user_id)
            .where(app_events.c.event_name == event_name)
            .where(app_events.c.created_at >= since)
        ).one()
    return {"count": int(row[0] or 0), "oldest_created_at": row[1]}


def _app_event_payload(user_id: str, event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id") or str(uuid4()),
        "user_id": str(user_id),
        "session_id": _clean_text(event.get("session_id"), 120),
        "event_name": _clean_text(event.get("event_name"), 80) or "unknown",
        "page": _clean_text(event.get("page"), 80),
        "target_type": _clean_text(event.get("target_type"), 80),
        "target_id": _clean_text(event.get("target_id"), 160),
        "metadata_json": event.get("metadata") if isinstance(event.get("metadata"), dict) else {},
        "client_created_at": _clean_text(event.get("client_created_at"), 80),
    }


def _clean_text(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def _app_event_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "session_id": row["session_id"],
        "event_name": row["event_name"],
        "page": row["page"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "metadata": row["metadata_json"],
        "client_created_at": row["client_created_at"],
        "created_at": _isoformat_utc(row["created_at"]),
    }
