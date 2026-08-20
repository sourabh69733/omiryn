"""Public contracts and batch selection for the background memory pipeline."""

from .context import build_memory_batch
from .models import (
    MemoryBatch,
    MemoryHandoff,
    MemoryMessage,
    MemoryOperation,
    MemoryProcessingState,
)
from .service import get_processing_state, save_processing_state

__all__ = [
    "MemoryBatch",
    "MemoryHandoff",
    "MemoryMessage",
    "MemoryOperation",
    "MemoryProcessingState",
    "build_memory_batch",
    "get_processing_state",
    "save_processing_state",
]
