"""Defines validated v3 memory proposals produced by background cognition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

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


@dataclass(frozen=True)
class MemoryAnalysisV3:
    """Fail-closed validation result for one v3 memory lane."""

    decision: str
    operations: tuple[MemoryAddProposal, ...]
    handoff: MemoryHandoff
    valid: bool
    errors: tuple[str, ...] = ()


__all__ = ["MemoryAddProposal", "MemoryAnalysisV3"]
