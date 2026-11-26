"""What a pick reads about each person, read once.

A pick looks at every pair of ready people, and each person is in many pairs. Readiness (all of a
person's memories, searched for the meet facts) and their memory vectors do not change between
two pairs of the same pick, so they are worked out the first time someone asks and kept for the
life of this object. One per pick or per check; never kept between picks, since both change as
people talk to Omi.
"""

from __future__ import annotations

from typing import Any

from .touchpoints import MemoryVectors


class PickReads:
    def __init__(self) -> None:
        self._readiness: dict[str, Any] = {}
        self._vectors: dict[str, MemoryVectors] = {}

    def readiness(self, user_id: str) -> Any:
        if user_id not in self._readiness:
            # Looked up at call time, like every other reader of readiness, so one patch reaches all.
            from .readiness import match_readiness

            self._readiness[user_id] = match_readiness(user_id)
        return self._readiness[user_id]

    def vectors(self, user_id: str) -> MemoryVectors:
        if user_id not in self._vectors:
            from .touchpoints import load_memory_vectors

            self._vectors[user_id] = load_memory_vectors(user_id)
        return self._vectors[user_id]


__all__ = ["PickReads"]
