"""Defines the provider-neutral v3 contract for durable agent memories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


MEMORY_SCHEMA_VERSION = 3


class MemoryKind(str, Enum):
    """How a memory is represented cognitively."""

    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    RELATIONSHIP = "relationship"
    PROCEDURAL = "procedural"


class MemoryPurpose(str, Enum):
    """Why a memory may be useful; this does not itself grant permission."""

    PROFILE = "profile"
    MATCHING = "matching"
    PERSONALIZATION = "personalization"


class MemoryUse(str, Enum):
    """Explicitly allowed product uses for a memory."""

    REPLY_CONTEXT = "reply_context"
    MATCHING = "matching"


class MemoryStatus(str, Enum):
    """Lifecycle state; corrections preserve history instead of overwriting it."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class MemorySensitivity(str, Enum):
    """Coarse privacy classification used by later retrieval policy."""

    STANDARD = "standard"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"


@dataclass(frozen=True)
class MemoryEvidence:
    """Traceable user evidence supporting one memory."""

    conversation_id: str
    exact_quote: str
    observed_at: datetime
    message_id: str | None = None
    message_index: int | None = None

    def __post_init__(self) -> None:
        if not self.conversation_id.strip():
            raise ValueError("memory evidence requires conversation_id")
        if not self.exact_quote.strip():
            raise ValueError("memory evidence requires an exact user quote")
        if self.message_id is None and self.message_index is None:
            raise ValueError("memory evidence requires message_id or message_index")
        if self.message_id is not None and not self.message_id.strip():
            raise ValueError("memory evidence message_id cannot be blank")
        if self.message_index is not None and self.message_index < 0:
            raise ValueError("memory evidence message_index cannot be negative")
        _require_aware_datetime("observed_at", self.observed_at)


@dataclass(frozen=True)
class MemoryRecord:
    """One durable memory; persistence owns its IDs and audit timestamps."""

    id: str
    user_id: str
    kind: MemoryKind
    purposes: frozenset[MemoryPurpose]
    key: str
    value: Any
    evidence: tuple[MemoryEvidence, ...]
    created_at: datetime
    updated_at: datetime
    allowed_uses: frozenset[MemoryUse] = frozenset({MemoryUse.REPLY_CONTEXT})
    status: MemoryStatus = MemoryStatus.ACTIVE
    sensitivity: MemorySensitivity = MemorySensitivity.STANDARD
    confidence: float = 0.5
    importance: float = 0.5
    occurred_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    last_reinforced_at: datetime | None = None
    supersedes_memory_id: str | None = None
    extractor: str | None = None
    extractor_model: str | None = None
    schema_version: int = MEMORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text("id", self.id)
        _require_text("user_id", self.user_id)
        _require_text("key", self.key)
        if not isinstance(self.kind, MemoryKind):
            raise ValueError("memory kind is invalid")
        if not self.purposes:
            raise ValueError("memory requires at least one purpose")
        if any(not isinstance(purpose, MemoryPurpose) for purpose in self.purposes):
            raise ValueError("memory purpose is invalid")
        if any(not isinstance(use, MemoryUse) for use in self.allowed_uses):
            raise ValueError("memory allowed use is invalid")
        if not isinstance(self.status, MemoryStatus):
            raise ValueError("memory status is invalid")
        if not isinstance(self.sensitivity, MemorySensitivity):
            raise ValueError("memory sensitivity is invalid")
        if self.value is None:
            raise ValueError("memory value cannot be null")
        if not self.evidence:
            raise ValueError("memory requires at least one evidence reference")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("memory confidence must be between 0 and 1")
        if not 0.0 <= self.importance <= 1.0:
            raise ValueError("memory importance must be between 0 and 1")
        if self.schema_version != MEMORY_SCHEMA_VERSION:
            raise ValueError(f"memory schema_version must be {MEMORY_SCHEMA_VERSION}")

        for name in (
            "created_at",
            "updated_at",
            "occurred_at",
            "valid_from",
            "valid_until",
            "last_reinforced_at",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_aware_datetime(name, value)

        if self.updated_at < self.created_at:
            raise ValueError("memory updated_at cannot precede created_at")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("memory valid_until cannot precede valid_from")
        if self.last_reinforced_at and self.last_reinforced_at < self.created_at:
            raise ValueError("memory last_reinforced_at cannot precede created_at")
        if self.supersedes_memory_id == self.id:
            raise ValueError("memory cannot supersede itself")


def _require_text(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"memory {name} cannot be blank")


def _require_aware_datetime(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"memory {name} must be timezone-aware")
