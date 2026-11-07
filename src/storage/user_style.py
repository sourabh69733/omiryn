"""Stores each user's talk-style counts (agent.matching.style), rebuilt with the user card."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from .database import ENGINE
from .schema import agent_user_style
from .utils import _protect_text, _require_user_id, _unprotect_text


def get_user_style(user_id: str) -> dict[str, Any] | None:
    owner_id = _require_user_id(user_id, "agent user style")
    with ENGINE.begin() as connection:
        value = connection.execute(
            select(agent_user_style.c.counts).where(agent_user_style.c.user_id == owner_id)
        ).scalar_one_or_none()
    if not value:
        return None
    counts = json.loads(_unprotect_text(owner_id, value))
    return counts if isinstance(counts, dict) else None


def set_user_style(user_id: str, counts: dict[str, Any]) -> dict[str, Any]:
    owner_id = _require_user_id(user_id, "agent user style")
    values = {
        "counts": _protect_text(owner_id, json.dumps(counts, ensure_ascii=False)),
        "message_count": int(counts.get("message_count") or 0),
        "built_at": func.now(),
    }
    with ENGINE.begin() as connection:
        updated = connection.execute(agent_user_style.update().where(agent_user_style.c.user_id == owner_id).values(**values))
        if not updated.rowcount:
            connection.execute(agent_user_style.insert().values(user_id=owner_id, **values))
    return counts


def user_style_built_at(user_id: str) -> datetime | None:
    owner_id = _require_user_id(user_id, "agent user style")
    with ENGINE.begin() as connection:
        value = connection.execute(
            select(agent_user_style.c.built_at).where(agent_user_style.c.user_id == owner_id)
        ).scalar_one_or_none()
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


__all__ = ["get_user_style", "set_user_style", "user_style_built_at"]
