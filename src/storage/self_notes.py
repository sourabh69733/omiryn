"""Stores the companion's notes about what it said itself."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from agent.shared.clock import utc_now

from .database import ENGINE
from .schema import agent_self_notes
from .utils import _isoformat_utc, _protect_text, _require_user_id, _unprotect_text

ACTIVE = "active"


def add_self_notes(user_id: str, conversation_id: str, notes: list[dict[str, Any]]) -> int:
    """Insert notes whose IDs are new; a replayed batch adds nothing twice."""
    owner_id = _require_user_id(user_id, "agent self note")
    if not notes:
        return 0
    now = utc_now()
    added = 0
    with ENGINE.begin() as connection:
        existing = set(
            connection.execute(
                select(agent_self_notes.c.id).where(
                    agent_self_notes.c.id.in_([note["id"] for note in notes])
                )
            ).scalars()
        )
        for note in notes:
            if note["id"] in existing:
                continue
            connection.execute(
                agent_self_notes.insert().values(
                    id=note["id"],
                    user_id=owner_id,
                    conversation_id=conversation_id,
                    message_index=int(note["message_index"]),
                    kind=note["kind"],
                    text=_protect_text(owner_id, note["text"]),
                    due_at=note.get("due_at"),
                    status=ACTIVE,
                    created_at=now,
                    updated_at=now,
                )
            )
            added += 1
    return added


def resolve_self_notes(user_id: str, resolutions: list[tuple[str, str]]) -> int:
    """Mark notes done (promise kept) or dropped (changed mind, no longer true)."""
    owner_id = _require_user_id(user_id, "agent self note")
    changed = 0
    with ENGINE.begin() as connection:
        for note_id, status in resolutions:
            result = connection.execute(
                agent_self_notes.update()
                .where(
                    agent_self_notes.c.id == note_id,
                    agent_self_notes.c.user_id == owner_id,
                    agent_self_notes.c.status == ACTIVE,
                )
                .values(status=status, updated_at=utc_now())
            )
            changed += int(result.rowcount or 0)
    return changed


def list_active_self_notes(user_id: str, limit: int = 40) -> list[dict[str, Any]]:
    """Newest first."""
    owner_id = _require_user_id(user_id, "agent self note")
    with ENGINE.begin() as connection:
        rows = (
            connection.execute(
                select(agent_self_notes)
                .where(agent_self_notes.c.user_id == owner_id, agent_self_notes.c.status == ACTIVE)
                .order_by(agent_self_notes.c.created_at.desc(), agent_self_notes.c.id)
                .limit(limit)
            )
            .mappings()
            .all()
        )
    return [
        {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "message_index": row["message_index"],
            "kind": row["kind"],
            "text": _unprotect_text(owner_id, row["text"]),
            "due_at": _isoformat_utc(row["due_at"]),
            "created_at": _isoformat_utc(row["created_at"]),
        }
        for row in rows
    ]


__all__ = [
    "add_self_notes",
    "list_active_self_notes",
    "resolve_self_notes",
]
