"""Persists append-only owner reviews for canonical V3 memories."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from agent.memory_engine.memories import MemoryStatus

from .database import ENGINE
from .memories import get_agent_memory
from .schema import agent_memories, agent_memory_reviews
from .utils import _isoformat_utc, _require_user_id


def review_agent_memory(
    memory_id: str,
    user_id: str,
    rating: str,
    *,
    reason: str | None = None,
    comment: str | None = None,
) -> dict[str, Any] | None:
    """Record owner feedback and update the reviewed memory in one transaction."""
    owner_id = _require_user_id(user_id, "agent memory review")
    normalized_rating = str(rating).strip().lower()
    if normalized_rating not in {"agree", "disagree"}:
        raise ValueError("memory review rating must be agree or disagree")
    normalized_reason = str(reason or "").strip().lower().replace(" ", "_")[:80] or None
    normalized_comment = str(comment or "").strip()[:1000] or None

    with ENGINE.begin() as connection:
        memory = (
            connection.execute(
                select(agent_memories).where(
                    agent_memories.c.id == memory_id,
                    agent_memories.c.user_id == owner_id,
                )
            )
            .mappings()
            .first()
        )
        if memory is None:
            return None

        now = datetime.now(UTC)
        if normalized_rating == "agree":
            update_values = {
                "status": MemoryStatus.ACTIVE.value,
                "confidence": max(float(memory["confidence"]), 0.9),
                "last_reinforced_at": now,
                "updated_at": now,
            }
        else:
            update_values = {
                "status": MemoryStatus.RETRACTED.value,
                "updated_at": now,
            }

        connection.execute(
            agent_memories.update()
            .where(
                agent_memories.c.id == memory_id,
                agent_memories.c.user_id == owner_id,
            )
            .values(**update_values)
        )
        review_id = str(uuid4())
        connection.execute(
            agent_memory_reviews.insert().values(
                id=review_id,
                user_id=owner_id,
                memory_id=memory_id,
                rating=normalized_rating,
                reason=normalized_reason,
                comment=normalized_comment,
                created_at=now,
                updated_at=now,
            )
        )
        review_row = (
            connection.execute(
                select(agent_memory_reviews).where(agent_memory_reviews.c.id == review_id)
            )
            .mappings()
            .one()
        )
        review_count = len(
            connection.execute(
                select(agent_memory_reviews.c.id).where(
                    agent_memory_reviews.c.user_id == owner_id,
                    agent_memory_reviews.c.memory_id == memory_id,
                )
            ).all()
        )

    updated_memory = get_agent_memory(memory_id, owner_id)
    if updated_memory is None:
        return None
    return {
        **updated_memory,
        "feedback": _review_payload(review_row, review_count),
    }


def latest_agent_memory_reviews(
    user_id: str,
    memory_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return each memory's latest review plus its append-only history count."""
    owner_id = _require_user_id(user_id, "agent memory review")
    with ENGINE.begin() as connection:
        query = (
            select(agent_memory_reviews)
            .where(agent_memory_reviews.c.user_id == owner_id)
            .order_by(
                agent_memory_reviews.c.created_at.desc(),
                agent_memory_reviews.c.id.desc(),
            )
        )
        if memory_ids is not None:
            if not memory_ids:
                return {}
            query = query.where(agent_memory_reviews.c.memory_id.in_(memory_ids))
        rows = connection.execute(query).mappings().all()

    latest: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for row in rows:
        memory_id = str(row["memory_id"])
        counts[memory_id] = counts.get(memory_id, 0) + 1
        latest.setdefault(memory_id, dict(row))
    return {
        memory_id: _review_payload(row, counts[memory_id])
        for memory_id, row in latest.items()
    }


def list_agent_memory_reviews(user_id: str, memory_id: str) -> list[dict[str, Any]]:
    """List one owned memory's review history in the order it was recorded."""
    owner_id = _require_user_id(user_id, "agent memory review")
    with ENGINE.begin() as connection:
        rows = (
            connection.execute(
                select(agent_memory_reviews)
                .where(
                    agent_memory_reviews.c.user_id == owner_id,
                    agent_memory_reviews.c.memory_id == memory_id,
                )
                .order_by(
                    agent_memory_reviews.c.created_at.asc(),
                    agent_memory_reviews.c.id.asc(),
                )
            )
            .mappings()
            .all()
        )
    return [_review_payload(row, index) for index, row in enumerate(rows, start=1)]


def _review_payload(row: Any, review_count: int) -> dict[str, Any]:
    return {
        "rating": row["rating"],
        "reason": row["reason"],
        "comment": row["comment"],
        "review_count": review_count,
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


__all__ = [
    "latest_agent_memory_reviews",
    "list_agent_memory_reviews",
    "review_agent_memory",
]
