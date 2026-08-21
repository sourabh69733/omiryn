"""Result contracts produced by the background cognition coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.memory_engine.processing.validation import MemoryAnalysis


@dataclass(frozen=True)
class BackgroundCognitionAnalysis:
    """Validated memory and thread lanes from one provider response."""

    decision: str
    memory: MemoryAnalysis
    thread: dict[str, Any]
    thread_operation: str
    valid: bool
    errors: tuple[str, ...] = ()


__all__ = ["BackgroundCognitionAnalysis"]
