"""Defines immutable, provider-neutral records for background memory batches."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MemoryScope = Literal["context", "new"]
MemoryOperationKind = Literal["add", "reinforce", "supersede", "retract", "noop"]


@dataclass(frozen=True)
class MemoryMessage:
    """One ordered message with explicit extraction and evidence permissions."""

    message_index: int
    role: str
    content: str
    scope: MemoryScope
    evidence_eligible: bool
    sent_at: str | None = None
    # Sent first by the companion (a nudge or greeting), not in answer to the user.
    initiated_by_companion: bool = False
    # The earlier message the user picked to answer: {"message_index", "text"}.
    replying_to: dict[str, Any] | None = None


@dataclass(frozen=True)
class SessionLogEntry:
    """What one chat session was about; keyed by its start time (UTC ISO)."""

    started_at: str
    ended_at: str
    gist: str
    unfinished: str = ""


@dataclass(frozen=True)
class MemoryHandoff:
    """Compact bridge carrying unresolved context between adjacent batches."""

    summary: str = ""
    active_people: tuple[str, ...] = ()
    active_topics: tuple[str, ...] = ()
    unresolved_references: tuple[str, ...] = ()
    # Rolling summary of the whole conversation so far, read by the companion (V3).
    conversation_summary: str = ""
    # One dated entry per session, newest last (V3).
    session_log: tuple[SessionLogEntry, ...] = ()


@dataclass(frozen=True)
class MemoryOperation:
    """A model proposal; the backend must validate it before any persistence."""

    operation: MemoryOperationKind
    data_point_type: str | None = None
    memory_basis: str | None = None
    category: str | None = None
    key: str | None = None
    label: str | None = None
    value: Any = None
    confidence: float | None = None
    evidence_message_indexes: tuple[int, ...] = ()
    target_memory_id: str | None = None


@dataclass(frozen=True)
class MemoryBatch:
    """Bounded background input containing new and context-only messages."""

    batch_key: str
    conversation_id: str
    user_id: str
    messages: tuple[MemoryMessage, ...]
    new_start_message_index: int
    new_end_message_index: int
    meaningful_user_message_count: int
    previous_handoff: MemoryHandoff = field(default_factory=MemoryHandoff)

    @property
    def new_messages(self) -> tuple[MemoryMessage, ...]:
        return tuple(message for message in self.messages if message.scope == "new")

    @property
    def context_messages(self) -> tuple[MemoryMessage, ...]:
        return tuple(message for message in self.messages if message.scope == "context")

    @property
    def evidence_message_indexes(self) -> tuple[int, ...]:
        return tuple(
            message.message_index for message in self.messages if message.evidence_eligible
        )


@dataclass(frozen=True)
class MemoryProcessingState:
    """Persistent high-water mark and handoff for exactly one conversation."""

    conversation_id: str
    user_id: str
    processed_through_message_index: int = -1
    last_batch_key: str | None = None
    handoff: MemoryHandoff = field(default_factory=MemoryHandoff)
    version: int = 0
    created_at: str | None = None
    updated_at: str | None = None

@dataclass(frozen=True)
class MemoryAnalysis:
    """A memory proposal that has passed the domain contract."""

    decision: str
    operations: tuple[MemoryOperation, ...]
    handoff: MemoryHandoff
    valid: bool
    errors: tuple[str, ...] = ()
