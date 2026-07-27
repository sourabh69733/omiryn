from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from .database import ENGINE
from .schema import data_requests
from .utils import _isoformat_utc


def save_data_request(request: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": request.get("id") or str(uuid4()),
        "user_id": str(request["user_id"]),
        "email": _clean_text(request.get("email"), 240),
        "request_type": _clean_text(request.get("request_type"), 40) or "export",
        "status": _clean_text(request.get("status"), 40) or "open",
        "message": _clean_text(request.get("message"), 2000),
        "metadata_json": request.get("metadata") if isinstance(request.get("metadata"), dict) else {},
    }
    with ENGINE.begin() as connection:
        connection.execute(data_requests.insert().values(**payload))
        row = connection.execute(
            select(data_requests).where(data_requests.c.id == payload["id"])
        ).mappings().first()
    return _data_request_from_row(row)


def list_user_data_requests(user_id: str) -> list[dict[str, Any]]:
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(data_requests)
            .where(data_requests.c.user_id == user_id)
            .order_by(data_requests.c.created_at.desc())
        ).mappings().all()
    return [_data_request_from_row(row) for row in rows]


def _clean_text(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def _data_request_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "email": row["email"],
        "request_type": row["request_type"],
        "status": row["status"],
        "message": row["message"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }
