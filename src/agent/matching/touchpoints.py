"""Touchpoints: pairs of memories, one from each person, that are about the same thing.

Code pairs each of A's memories with B's most similar one by cosine between the stored memory
embeddings (the same vectors recall uses) and keeps the pairs above a floor. The judge reads them
and says whether each is shared, complementary or a clash; code never decides that.

What leaves an account: only active, standard-sensitivity memories that are not how-to-talk rules,
with the names they mention taken out. A touchpoint may back a reason the other person sees only
when both memories carry the matching purpose; everything else is context for the judge alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.memory_engine.memories.ranking import embedding_similarity
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
    vectors_a = {str(item["memory_id"]): item for item in embeddings_a}
    vectors_b = {str(item["memory_id"]): item for item in embeddings_b}
    shareable_a = [m for m in memories_a if shareable(m) and str(m.get("id")) in vectors_a]
    shareable_b = [m for m in memories_b if shareable(m) and str(m.get("id")) in vectors_b]
    scored: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for a in shareable_a:
        for b in shareable_b:
            similarity = embedding_similarity(vectors_a[str(a["id"])], vectors_b[str(b["id"])])
            if similarity is not None and similarity >= floor:
                scored.append((similarity, a, b))
    scored.sort(key=lambda item: -item[0])
    used_a: set[str] = set()
    used_b: set[str] = set()
    points: list[Touchpoint] = []
    for similarity, a, b in scored:
        if str(a["id"]) in used_a or str(b["id"]) in used_b:
            continue
        used_a.add(str(a["id"]))
        used_b.add(str(b["id"]))
        points.append(
            Touchpoint(str(a["id"]), str(b["id"]), memory_text(a), memory_text(b), similarity, reason_allowed(a) and reason_allowed(b))
        )
        if len(points) == limit:
            break
    return points


def pair_touchpoints(user_a: str, user_b: str, *, limit: int = TOUCHPOINT_LIMIT) -> list[Touchpoint]:
    """Touchpoints for two users from what is stored; empty when either has no embeddings."""
    from storage import list_agent_memories
    from storage.memory_embeddings import list_agent_memory_embeddings

    memories_a = [m for m in list_agent_memories(user_a) if shareable(m)]
    memories_b = [m for m in list_agent_memories(user_b) if shareable(m)]
    if not memories_a or not memories_b:
        return []
    embeddings_a = list_agent_memory_embeddings(user_a, [str(m["id"]) for m in memories_a])
    embeddings_b = list_agent_memory_embeddings(user_b, [str(m["id"]) for m in memories_b])
    return touchpoints(memories_a, embeddings_a, memories_b, embeddings_b, limit=limit)


__all__ = ["SIMILARITY_FLOOR", "TOUCHPOINT_LIMIT", "Touchpoint", "memory_text", "pair_touchpoints", "reason_allowed", "shareable", "touchpoints"]
