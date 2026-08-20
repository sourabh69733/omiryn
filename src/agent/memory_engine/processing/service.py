"""Maps background-memory domain records to the private storage boundary."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from storage.memory_processing import (
    MemoryProcessingStateConflictError,
    get_memory_processing_state,
    save_memory_processing_state,
)

from .models import MemoryHandoff, MemoryProcessingState


def get_processing_state(
    conversation_id: str,
    user_id: str,
) -> MemoryProcessingState | None:
    row = get_memory_processing_state(conversation_id, user_id)
    return _state_from_row(row) if row else None


def save_processing_state(state: MemoryProcessingState) -> MemoryProcessingState:
    _validate_state(state)
    payload = asdict(state)
    payload["handoff"] = asdict(state.handoff)
    row = save_memory_processing_state(payload, expected_version=state.version)
    return _state_from_row(row)


def _state_from_row(row: dict[str, Any]) -> MemoryProcessingState:
    raw_handoff = row.get("handoff") if isinstance(row.get("handoff"), dict) else {}
    handoff = MemoryHandoff(
        summary=str(raw_handoff.get("summary") or ""),
        active_people=tuple(str(value) for value in raw_handoff.get("active_people") or ()),
        active_topics=tuple(str(value) for value in raw_handoff.get("active_topics") or ()),
        unresolved_references=tuple(
            str(value) for value in raw_handoff.get("unresolved_references") or ()
        ),
    )
    return MemoryProcessingState(
        conversation_id=str(row["conversation_id"]),
        user_id=str(row["user_id"]),
        processed_through_message_index=int(row["processed_through_message_index"]),
        last_batch_key=row.get("last_batch_key"),
        handoff=handoff,
        version=int(row.get("version") or 0),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _validate_state(state: MemoryProcessingState) -> None:
    if not state.conversation_id or not state.user_id:
        raise ValueError("memory processing state requires conversation_id and user_id")
    if state.processed_through_message_index < -1:
        raise ValueError("processed_through_message_index cannot be less than -1")
    if len(state.handoff.summary) > 2000:
        raise ValueError("memory handoff summary cannot exceed 2000 characters")
    for name, values in (
        ("active_people", state.handoff.active_people),
        ("active_topics", state.handoff.active_topics),
        ("unresolved_references", state.handoff.unresolved_references),
    ):
        if len(values) > 20:
            raise ValueError(f"memory handoff {name} cannot contain more than 20 items")
        if any(not value.strip() or len(value) > 160 for value in values):
            raise ValueError(f"memory handoff {name} contains an invalid item")


__all__ = [
    "MemoryProcessingStateConflictError",
    "get_processing_state",
    "save_processing_state",
]
