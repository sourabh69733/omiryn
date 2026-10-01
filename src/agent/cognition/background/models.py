"""Result contracts produced by the background cognition coordinator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.memory_engine.memories.operations import MemoryAnalysisV3
from agent.memory_engine.memories.self_notes import SelfNoteChanges
from agent.memory_engine.processing.validation import MemoryAnalysis


@dataclass(frozen=True)
class BackgroundCognitionAnalysis:
    """Validated memory and thread lanes from one provider response."""

    decision: str
    memory: MemoryAnalysis | MemoryAnalysisV3
    thread: dict[str, Any]
    thread_operation: str
    valid: bool
    errors: tuple[str, ...] = ()
    # Rewritten per-user card; None keeps the stored one.
    user_card: str | None = None
    self_notes: SelfNoteChanges = SelfNoteChanges()
    # Vibe area lines the model rewrote; empty keeps the stored card.
    vibe: dict[str, str] = field(default_factory=dict)


__all__ = ["BackgroundCognitionAnalysis"]
