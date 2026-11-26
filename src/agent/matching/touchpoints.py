"""Touchpoints: pairs of memories, one from each person, that are about the same thing.

Code pairs each of A's memories with B's most similar one by cosine between the stored memory
embeddings (the same vectors recall uses) and keeps the pairs above a floor. The cosines for two
people are one matrix product (numpy); a pool of forty is 780 pairs of people, each with every
memory of one against every memory of the other, which a Python loop does not finish in time. The judge reads them
and says whether each is shared, complementary or a clash; code never decides that.

What leaves an account: only active, standard-sensitivity memories that are not how-to-talk rules,
with the names they mention taken out. A touchpoint may back a reason the other person sees only
when both memories carry the matching purpose; everything else is context for the judge alone.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from agent.shared.memory_models import MemoryKind, MemoryPurpose, MemorySensitivity

TOUCHPOINT_LIMIT = 6
# Cosine below this is two memories about different things. First guess for bge-m3; the judge
# evaluation (design section 8.5) is where it gets measured.
SIMILARITY_FLOOR = 0.55
MAX_TEXT_CHARS = 200
_NAME_STAND_IN = "[name]"


@dataclass(frozen=True)
class Touchpoint:
    memory_a: str
    memory_b: str
    text_a: str
    text_b: str
    similarity: float
    reason_ok: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "memory_a": self.memory_a,
            "memory_b": self.memory_b,
            "a": self.text_a,
            "b": self.text_b,
            "similarity": round(self.similarity, 3),
            "reason_ok": self.reason_ok,
        }


def shareable(memory: dict[str, Any]) -> bool:
    """May this memory be in a pack at all: active, standard sensitivity, not a how-to-talk rule,
    and with something to read."""
    return (
        memory.get("status", "active") == "active"
        and str(memory.get("sensitivity") or MemorySensitivity.STANDARD.value) == MemorySensitivity.STANDARD.value
        and memory.get("kind") != MemoryKind.PROCEDURAL.value
        and bool(memory_text(memory))
    )


def reason_allowed(memory: dict[str, Any]) -> bool:
    return MemoryPurpose.MATCHING.value in set(memory.get("purposes") or [])


def memory_text(memory: dict[str, Any]) -> str:
    """The statement with the names it mentions taken out, shortened."""
    text = " ".join(str(memory.get("statement") or memory.get("value") or "").split())
    for name in memory.get("about") or []:
        name = str(name).strip()
        if len(name) >= 2:
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", _NAME_STAND_IN, text, flags=re.IGNORECASE)
    return text[:MAX_TEXT_CHARS]


# The space a stored vector is in: only two vectors of the same provider, model and size compare.
Space = tuple[Any, Any, Any, int]


@dataclass(frozen=True)
class MemoryVectors:
    """One person's shareable memories that have a stored vector, ready to compare: per space, the
    memory ids and one matrix with a row per memory, each row scaled to length one. Built once per
    person, so the cosines between two people are one matrix product and not a Python loop over
    every pair of memories."""

    memories: dict[str, dict[str, Any]]
    spaces: dict[Space, tuple[list[str], np.ndarray]]


def memory_vectors(memories: list[dict[str, Any]], embeddings: list[dict[str, Any]]) -> MemoryVectors:
    """Keep the shareable memories with a usable vector; a vector of the wrong size or of length
    zero compares with nothing, as before."""
    by_id = {str(m.get("id")): m for m in memories if shareable(m)}
    grouped: dict[Space, tuple[list[str], list[np.ndarray]]] = {}
    kept: dict[str, dict[str, Any]] = {}
    for item in embeddings:
        memory_id = str(item.get("memory_id"))
        values = item.get("values")
        if memory_id not in by_id or memory_id in kept or not isinstance(values, list) or not values:
            continue
        try:
            row = np.asarray(values, dtype=np.float64)
        except (TypeError, ValueError):
            continue
        norm = float(np.linalg.norm(row))
        if row.ndim != 1 or not norm or not np.isfinite(norm):
            continue
        ids, rows = grouped.setdefault((item.get("provider"), item.get("model"), item.get("dimensions"), len(values)), ([], []))
        ids.append(memory_id)
        rows.append(row / norm)
        kept[memory_id] = by_id[memory_id]
    return MemoryVectors(kept, {space: (ids, np.vstack(rows)) for space, (ids, rows) in grouped.items()})


def touchpoints_between(a: MemoryVectors, b: MemoryVectors, *, limit: int = TOUCHPOINT_LIMIT, floor: float = SIMILARITY_FLOOR) -> list[Touchpoint]:
    """Best pairs across the two people, each memory used at most once, strongest first."""
    scored: list[tuple[float, str, str]] = []
    for space, (ids_a, rows_a) in a.spaces.items():
        if space not in b.spaces:
            continue
        ids_b, rows_b = b.spaces[space]
        similarity = np.clip(rows_a @ rows_b.T, 0.0, 1.0)
        for i, j in zip(*np.nonzero(similarity >= floor), strict=True):
            scored.append((float(similarity[i, j]), ids_a[i], ids_b[j]))
    scored.sort(key=lambda item: -item[0])
    used_a: set[str] = set()
    used_b: set[str] = set()
    points: list[Touchpoint] = []
    for similarity, id_a, id_b in scored:
        if id_a in used_a or id_b in used_b:
            continue
        used_a.add(id_a)
        used_b.add(id_b)
        memory_a, memory_b = a.memories[id_a], b.memories[id_b]
        points.append(Touchpoint(id_a, id_b, memory_text(memory_a), memory_text(memory_b), similarity, reason_allowed(memory_a) and reason_allowed(memory_b)))
        if len(points) == limit:
            break
    return points


def touchpoints(
    memories_a: list[dict[str, Any]],
    embeddings_a: list[dict[str, Any]],
    memories_b: list[dict[str, Any]],
    embeddings_b: list[dict[str, Any]],
    *,
    limit: int = TOUCHPOINT_LIMIT,
    floor: float = SIMILARITY_FLOOR,
) -> list[Touchpoint]:
    """Best pairs across the two sets, each memory used at most once, strongest first."""
    return touchpoints_between(memory_vectors(memories_a, embeddings_a), memory_vectors(memories_b, embeddings_b), limit=limit, floor=floor)


def load_memory_vectors(user_id: str) -> MemoryVectors:
    """One person's shareable memories and their vectors from what is stored; empty when there are none."""
    from storage import list_agent_memories
    from storage.memory_embeddings import list_agent_memory_embeddings

    memories = [m for m in list_agent_memories(user_id) if shareable(m)]
    if not memories:
        return MemoryVectors({}, {})
    return memory_vectors(memories, list_agent_memory_embeddings(user_id, [str(m["id"]) for m in memories]))


def pair_touchpoints(
    user_a: str, user_b: str, *, limit: int = TOUCHPOINT_LIMIT, vectors: Callable[[str], MemoryVectors] | None = None
) -> list[Touchpoint]:
    """Touchpoints for two users from what is stored; empty when either has no embeddings.

    `vectors` gives a person's vectors when the caller already holds them: a pick over a pool
    reads each person once (agent.matching.reads), not once per pair they are in.
    """
    load = vectors or load_memory_vectors
    a = load(user_a)
    if not a.memories:
        return []
    b = load(user_b)
    if not b.memories:
        return []
    return touchpoints_between(a, b, limit=limit)


__all__ = [
    "SIMILARITY_FLOOR", "TOUCHPOINT_LIMIT", "MemoryVectors", "Touchpoint", "load_memory_vectors", "memory_text", "memory_vectors",
    "pair_touchpoints", "reason_allowed", "shareable", "touchpoints", "touchpoints_between",
]
