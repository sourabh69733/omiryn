"""Selects bounded existing-memory context for V3 lifecycle reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import MemoryStatus
from .ranking import bounded_score, recency_score, searchable_memory_text, text_relevance


def select_reconciliation_candidates(
    memories: list[dict[str, Any]],
    user_text: str,
    *,
    limit: int = 8,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return active memories most useful for add/reinforce/correct decisions."""
    if limit <= 0:
        return []
    current_time = now or datetime.now(UTC)
    eligible = [
        memory
        for memory in memories
        if memory.get("status") == MemoryStatus.ACTIVE.value
    ]
    return sorted(
        eligible,
        key=lambda memory: (
            -_reconciliation_score(memory, user_text, current_time),
            str(memory.get("id") or ""),
        ),
    )[:limit]


def _reconciliation_score(memory: dict[str, Any], user_text: str, now: datetime) -> float:
    relevance = text_relevance(user_text, searchable_memory_text(memory))
    return (
        relevance * 0.7
        + bounded_score(memory.get("importance")) * 0.15
        + bounded_score(memory.get("confidence")) * 0.1
        + recency_score(memory.get("updated_at"), now) * 0.05
    )


__all__ = ["select_reconciliation_candidates"]
