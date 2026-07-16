from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from .database import ENGINE
from .schema import public_events, public_leads
from .utils import _isoformat_utc


def save_public_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": event.get("id") or str(uuid4()),
        "session_id": _clean_text(event.get("session_id"), 120) or str(uuid4()),
        "event_name": _clean_text(event.get("event_name"), 80) or "unknown",
        "path": _clean_text(event.get("path"), 300) or "/",
        "referrer": _clean_text(event.get("referrer"), 500),
        "metadata_json": event.get("metadata") if isinstance(event.get("metadata"), dict) else {},
    }
    with ENGINE.begin() as connection:
        connection.execute(public_events.insert().values(**payload))
        row = connection.execute(
            select(public_events).where(public_events.c.id == payload["id"])
        ).mappings().first()
    return _public_event_from_row(row)


def save_public_lead(lead: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": lead.get("id") or str(uuid4()),
        "session_id": _clean_text(lead.get("session_id"), 120),
        "name": _clean_text(lead.get("name"), 120),
        "contact": _clean_text(lead.get("contact"), 240) or "",
        "channel": _clean_text(lead.get("channel"), 40) or "email",
        "intent": _clean_text(lead.get("intent"), 80) or "feedback",
        "message": _clean_text(lead.get("message"), 1000),
        "metadata_json": lead.get("metadata") if isinstance(lead.get("metadata"), dict) else {},
    }
    with ENGINE.begin() as connection:
        connection.execute(public_leads.insert().values(**payload))
        row = connection.execute(
            select(public_leads).where(public_leads.c.id == payload["id"])
        ).mappings().first()
    return _public_lead_from_row(row)


def _clean_text(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def _public_event_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "event_name": row["event_name"],
        "path": row["path"],
        "referrer": row["referrer"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _public_lead_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "name": row["name"],
        "contact": row["contact"],
        "channel": row["channel"],
        "intent": row["intent"],
        "message": row["message"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }
