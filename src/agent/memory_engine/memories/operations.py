"""Defines validated v3 memory proposals produced by background cognition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeAlias

from agent.memory_engine.processing.models import MemoryHandoff

from .models import MemoryKind, MemoryPurpose, MemorySensitivity


@dataclass(frozen=True)
class MemoryAddProposal:
    """One evidence-backed durable memory proposed for atomic insertion."""

    kind: MemoryKind
    purposes: frozenset[MemoryPurpose]
    key: str
    value: Any
    sensitivity: MemorySensitivity
    confidence: float
    importance: float
    evidence_message_indexes: tuple[int, ...]
    occurred_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    statement: str | None = None


@dataclass(frozen=True)
class MemoryReinforceProposal:
    """New evidence that strengthens an existing memory without changing it."""

    target_memory_id: str
    confidence: float
    importance: float
    evidence_message_indexes: tuple[int, ...]


@dataclass(frozen=True)
class MemorySupersedeProposal:
    """A corrected replacement that preserves the previous memory's history."""

    target_memory_id: str
    replacement: MemoryAddProposal


@dataclass(frozen=True)
class MemoryRetractProposal:
    """Evidence that an existing memory must no longer be treated as true."""

    target_memory_id: str
    evidence_message_indexes: tuple[int, ...]


MemoryProposalV3: TypeAlias = (
    MemoryAddProposal | MemoryReinforceProposal | MemorySupersedeProposal | MemoryRetractProposal
)


@dataclass(frozen=True)
class MemoryAnalysisV3:
    """Fail-closed validation result for one v3 memory lane."""

    decision: str
    operations: tuple[MemoryProposalV3, ...]
    handoff: MemoryHandoff
    valid: bool
    errors: tuple[str, ...] = ()


__all__ = ["MemoryAddProposal", "MemoryAnalysisV3"]
