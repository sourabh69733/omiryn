"""Stores each user's match notes (agent.matching.notes): who they are, in short notes with proof."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from .database import ENGINE
from .schema import agent_match_notes
from .utils import _protect_text, _require_user_id, _unprotect_text


def get_match_notes(user_id: str) -> dict[str, Any] | None:
    """{"version", "notes": [...], "covered_upto", "messages_seen"} or None when never built."""
    owner_id = _require_user_id(user_id, "agent match notes")
    with ENGINE.begin() as connection:
        value = connection.execute(select(agent_match_notes.c.notes).where(agent_match_notes.c.user_id == owner_id)).scalar_one_or_none()
    if not value:
        return None
    stored = json.loads(_unprotect_text(owner_id, value))
    return stored if isinstance(stored, dict) and isinstance(stored.get("notes"), list) else None


def set_match_notes(user_id: str, stored: dict[str, Any]) -> dict[str, Any]:
    owner_id = _require_user_id(user_id, "agent match notes")
    values = {
        "notes": _protect_text(owner_id, json.dumps(stored, ensure_ascii=False)),
        "note_count": len(stored.get("notes") or []),
        "built_at": func.now(),
    }
    with ENGINE.begin() as connection:
        updated = connection.execute(agent_match_notes.update().where(agent_match_notes.c.user_id == owner_id).values(**values))
        if not updated.rowcount:
            connection.execute(agent_match_notes.insert().values(user_id=owner_id, **values))
    return stored


def match_notes_built_at(user_id: str) -> datetime | None:
    owner_id = _require_user_id(user_id, "agent match notes")
    with ENGINE.begin() as connection:
        value = connection.execute(select(agent_match_notes.c.built_at).where(agent_match_notes.c.user_id == owner_id)).scalar_one_or_none()
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


__all__ = ["get_match_notes", "match_notes_built_at", "set_match_notes"]
