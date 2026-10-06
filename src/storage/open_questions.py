"""Stores what background cognition was unsure about, until the user's answer settles it."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from agent.shared.clock import utc_now

from .database import ENGINE
from .schema import agent_open_questions
from .utils import _isoformat_utc, _protect_text, _require_user_id, _unprotect_text

OPEN = "open"
QUESTION_LIFETIME = timedelta(days=14)


def add_open_questions(user_id: str, conversation_id: str, questions: list[dict[str, Any]]) -> int:
    """Insert questions whose IDs are new; a replayed batch adds nothing twice."""
    owner_id = _require_user_id(user_id, "agent open question")
    if not questions:
        return 0
    now = utc_now()
    added = 0
    with ENGINE.begin() as connection:
        existing = set(
            connection.execute(
                select(agent_open_questions.c.id).where(
                    agent_open_questions.c.id.in_([question["id"] for question in questions])
                )
            ).scalars()
        )
        for question in questions:
            if question["id"] in existing:
                continue
            connection.execute(
                agent_open_questions.insert().values(
                    id=question["id"],
                    user_id=owner_id,
                    conversation_id=conversation_id,
                    message_index=int(question["message_index"]),
                    text=_protect_text(owner_id, question["text"]),
                    about_memory_ids=json.dumps(list(question.get("about_memory_ids") or [])),
                    status=OPEN,
                    offered_count=0,
                    expires_at=now + QUESTION_LIFETIME,
                    created_at=now,
                    updated_at=now,
                )
            )
            added += 1
    return added


def resolve_open_questions(user_id: str, resolutions: list[tuple[str, str]]) -> int:
    """Close questions: answered (the user settled it) or dropped (no longer matters)."""
    owner_id = _require_user_id(user_id, "agent open question")
    changed = 0
    with ENGINE.begin() as connection:
        for question_id, status in resolutions:
            result = connection.execute(
                agent_open_questions.update()
                .where(
                    agent_open_questions.c.id == question_id,
                    agent_open_questions.c.user_id == owner_id,
                    agent_open_questions.c.status == OPEN,
                )
                .values(status=status, updated_at=utc_now())
            )
            changed += int(result.rowcount or 0)
    return changed


def list_open_questions(user_id: str, *, now: datetime | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Open, unexpired questions, oldest first (asked in the order they came up)."""
    owner_id = _require_user_id(user_id, "agent open question")
    with ENGINE.begin() as connection:
        rows = (
            connection.execute(
                select(agent_open_questions)
                .where(
                    agent_open_questions.c.user_id == owner_id,
                    agent_open_questions.c.status == OPEN,
                    agent_open_questions.c.expires_at > (now or utc_now()),
                )
                .order_by(agent_open_questions.c.created_at, agent_open_questions.c.id)
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
            "text": _unprotect_text(owner_id, row["text"]),
            "about_memory_ids": json.loads(row["about_memory_ids"] or "[]"),
            "offered_session": row["offered_session"],
            "offered_count": int(row["offered_count"] or 0),
            "created_at": _isoformat_utc(row["created_at"]),
        }
        for row in rows
    ]


def mark_open_question_offered(user_id: str, question_id: str, session: str) -> None:
    """Count one more reply in this session that saw the question."""
    owner_id = _require_user_id(user_id, "agent open question")
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(agent_open_questions.c.offered_session, agent_open_questions.c.offered_count).where(
                agent_open_questions.c.id == question_id,
                agent_open_questions.c.user_id == owner_id,
            )
        ).first()
        if row is None:
            return
        count = int(row[1] or 0) + 1 if row[0] == session else 1
        connection.execute(
            agent_open_questions.update()
            .where(agent_open_questions.c.id == question_id, agent_open_questions.c.user_id == owner_id)
            .values(offered_session=session, offered_count=count)
        )


__all__ = [
    "add_open_questions",
    "list_open_questions",
    "mark_open_question_offered",
    "resolve_open_questions",
]
