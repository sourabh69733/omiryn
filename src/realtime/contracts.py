"""Defines the stable event envelope shared by agent and human chat."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

RealtimeScope = Literal["user", "conversation"]


@dataclass(frozen=True)
class RealtimeEvent:
    """A versioned delivery notification; persistent storage remains authoritative."""

    type: str
    scope: RealtimeScope
    scope_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    sequence: int | None = None
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    version: int = 1

    def __post_init__(self) -> None:
        if not self.type.strip() or len(self.type) > 100:
            raise ValueError("Realtime event type must be 1-100 characters.")
        if not self.scope_id.strip() or len(self.scope_id) > 160:
            raise ValueError("Realtime event scope_id must be 1-160 characters.")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("Realtime event sequence cannot be negative.")
        if self.version != 1:
            raise ValueError("Unsupported realtime event version.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "sequence": self.sequence,
            "occurred_at": self.occurred_at,
            "version": self.version,
            "payload": self.payload,
        }


def conversation_event(
    event_type: str,
    conversation_id: str,
    *,
    payload: dict[str, Any] | None = None,
    sequence: int | None = None,
) -> RealtimeEvent:
    return RealtimeEvent(
        type=event_type,
        scope="conversation",
        scope_id=conversation_id,
        payload=payload or {},
        sequence=sequence,
    )


def user_event(
    event_type: str,
    user_id: str,
    *,
    payload: dict[str, Any] | None = None,
) -> RealtimeEvent:
    return RealtimeEvent(
        type=event_type,
        scope="user",
        scope_id=user_id,
        payload=payload or {},
    )
