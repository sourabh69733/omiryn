"""Canonical data-point domain models shared by extraction, storage, and retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class DataPoint:
    user_id: str
    category: str
    key: str
    value: dict[str, Any]
    label: str
    confidence: float = 0.5
    fact_type: str = "matching_fact"
    confidence_state: str = "active"
    source_kind: str = "agent_chat"
    source_id: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    status: str = "active"
    visibility: str = "internal"
    used_for_matching: bool = True
    used_for_chat_context: bool = False
