"""Records who did what to private data, with IDs and counts only, never content."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from .database import ENGINE
from .schema import audit_events
from .utils import _isoformat_utc

logger = logging.getLogger(__name__)

AUDIT_ROLES = {"user", "admin", "system"}


def record_audit_event(
    action: str,
    *,
    actor_id: str | None,
    actor_role: str,
    target_user_id: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Write one audit row. A failure is logged and never breaks the action being audited."""
    if actor_role not in AUDIT_ROLES:
        raise ValueError(f"unknown audit actor role: {actor_role}")
    try:
        with ENGINE.begin() as connection:
            connection.execute(
                audit_events.insert().values(
                    id=str(uuid4()),
                    actor_id=actor_id,
                    actor_role=actor_role,
                    action=action,
                    target_user_id=target_user_id,
                    target_id=target_id,
                    detail_json=_counts_only(detail or {}),
                )
            )
    except Exception:
        logger.exception("audit.write_failed action=%s", action)


def list_audit_events(*, target_user_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    statement = select(audit_events).order_by(audit_events.c.created_at.desc()).limit(max(1, min(limit, 500)))
    if target_user_id:
        statement = statement.where(audit_events.c.target_user_id == target_user_id)
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [
        {
            "id": row["id"],
            "actor_id": row["actor_id"],
            "actor_role": row["actor_role"],
            "action": row["action"],
            "target_user_id": row["target_user_id"],
            "target_id": row["target_id"],
            "detail": row["detail_json"] or {},
            "created_at": _isoformat_utc(row["created_at"]),
        }
        for row in rows
    ]


def _counts_only(detail: dict[str, Any]) -> dict[str, Any]:
    """Numbers, booleans and short labels pass; anything that could be content is dropped."""
    kept: dict[str, Any] = {}
    for key, value in detail.items():
        if isinstance(value, (bool, int, float)) or value is None:
            kept[key] = value
        elif isinstance(value, str) and len(value) <= 64 and " " not in value:
            kept[key] = value
    return kept


__all__ = ["list_audit_events", "record_audit_event"]
