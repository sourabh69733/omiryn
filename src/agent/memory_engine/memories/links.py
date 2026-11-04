"""Links between memories: two memories that are about the same person, place or thing.

The background model records the names on each memory (`about`). A message that names someone brings
every memory about that name, even one that only says "their sister". Proof and time stay on each
memory. Only a name the message says leads anywhere: following links from search matches pulled in
off-topic memories ("new laptop" matched a new job, then brought the sister's birthday).
"""

from __future__ import annotations

import re
from typing import Any

from .ranking import bounded_score

MAX_NAMES = 5
MAX_NAME_CHARS = 60
LINKED_MEMORY_LIMIT = 3


def normalize_about(value: Any) -> tuple[str, ...]:
    """The names as stored: trimmed, once each. Anything that is not a short name is dropped."""
    if not isinstance(value, (list, tuple)):
        return ()
    names: dict[str, str] = {}
    for item in value:
        name = " ".join(item.split()) if isinstance(item, str) else ""
        if name and len(name) <= MAX_NAME_CHARS:
            names.setdefault(name.casefold(), name)
    return tuple(names.values())[:MAX_NAMES]


def memory_names(memory: dict[str, Any]) -> set[str]:
    return {str(name).casefold() for name in memory.get("about") or []}


def names_in_text(text: str, names: set[str]) -> set[str]:
    """Which of these names the text says, as whole words."""
    lowered = text.casefold()
    return {name for name in names if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", lowered)}


def linked_memories(
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    user_text: str,
    *,
    limit: int = LINKED_MEMORY_LIMIT,
) -> list[dict[str, Any]]:
    """Memories not selected that are about a name the message says, strongest first. `candidates`
    are already safe to use in a reply."""
    known = set().union(*(memory_names(memory) for memory in candidates)) if candidates else set()
    said = names_in_text(user_text, known)
    if not said:
        return []
    chosen = {str(memory.get("id")) for memory in selected}
    linked = [
        memory
        for memory in candidates
        if str(memory.get("id")) not in chosen and memory_names(memory) & said
    ]
    return sorted(
        linked,
        key=lambda memory: (
            -(bounded_score(memory.get("importance")) + bounded_score(memory.get("confidence"))),
            str(memory.get("id") or ""),
        ),
    )[:limit]


__all__ = ["LINKED_MEMORY_LIMIT", "linked_memories", "memory_names", "names_in_text", "normalize_about"]
