"""Selects canonical V3 memories that may inform matching discovery progress."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import MemoryPurpose, MemorySensitivity, MemoryStatus, MemoryUse
from .ranking import aware_datetime


def matching_progress_memories(
    user_id: str,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return active matching knowledge permitted for companion reply planning."""
    from storage.memories import list_agent_memories

    current_time = now or datetime.now(UTC)
    return [
        memory
        for memory in list_agent_memories(user_id)
        if _eligible_for_matching_progress(memory, current_time)
    ]


def _eligible_for_matching_progress(memory: dict[str, Any], now: datetime) -> bool:
    if memory.get("status") != MemoryStatus.ACTIVE.value:
        return False
    if MemoryPurpose.MATCHING.value not in set(memory.get("purposes") or []):
        return False
    if MemoryUse.REPLY_CONTEXT.value not in set(memory.get("allowed_uses") or []):
        return False
    if memory.get("sensitivity") == MemorySensitivity.HIGHLY_SENSITIVE.value:
        return False

    valid_from = aware_datetime(memory.get("valid_from"))
    if valid_from is not None and now < valid_from:
        return False
    valid_until = aware_datetime(memory.get("valid_until"))
    return valid_until is None or now < valid_until


__all__ = ["matching_progress_memories"]
