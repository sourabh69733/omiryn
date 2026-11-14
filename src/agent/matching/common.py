"""What most people in a group share says nothing about a pair.

A model writing one person's notes cannot know what is ordinary: in one test group every person
had a humour note about "turning daily struggles into absurd jokes", and the judge gave it as the
reason for almost any two of them. Code can know. Each match note is compared with everyone
else's notes of the same kind, by meaning; a note that at least half of the others also have is
marked common. The judge sees the mark, a common note cannot back a reason, and it does not count
towards a pair's pull (agent.matching.choose).

One embedding call for the whole group, when the pick runs. With too few people to say what is
ordinary, or when the embedding call fails, nothing is marked.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import replace

from .choose import Loaded

logger = logging.getLogger(__name__)

# Fewer people with notes than this and "most of the group" means one or two others.
MIN_GROUP = 5
# Two notes this close in meaning say the same thing. Measured on the seeded test people
# (design section 12): notes everyone shared were 0.70 to 0.90 apart from most others, notes that
# set a person apart were under 0.70 for all but one other.
SAME_MEANING = 0.70
# Share of the other people who must have such a note for it to be common.
COMMON_SHARE = 0.5


def common_note_ids(notes: dict[str, list[tuple[str, str, list[float]]]]) -> dict[str, set[str]]:
    """person -> ids of their notes that most others share. `notes` holds, per person,
    (note id, kind, vector). Pure: the vectors come from the caller."""
    people = [ref for ref, items in notes.items() if items]
    out: dict[str, set[str]] = {ref: set() for ref in notes}
    if len(people) < MIN_GROUP:
        return out
    for ref in people:
        others = [other for other in people if other != ref]
        for note_id, kind, vector in notes[ref]:
            sharing = sum(
                1 for other in others
                if any(other_kind == kind and _cosine(vector, other_vector) >= SAME_MEANING for _, other_kind, other_vector in notes[other])
            )
            if sharing >= math.ceil(COMMON_SHARE * len(others)):
                out[ref].add(note_id)
    return out


async def mark_common(people: dict[str, Loaded]) -> dict[str, Loaded]:
    """The same people with their common match notes marked. Give it the whole group, also the
    ones who will not be ranked this time: what is ordinary is a fact about the group."""
    from agent.memory_engine.memories.embeddings import memory_embedding_target, provider_embeddings

    rows = [(ref, note.note_id, note.area or "", _nameless(note.text, person.name)) for ref, person in people.items() for note in person.lines if note.note_id]
    if len({ref for ref, *_ in rows}) < MIN_GROUP:
        return people
    try:
        target = memory_embedding_target()
        if target is None:
            return people
        vectors = await provider_embeddings(provider=target[0], model=target[1], inputs=[text for *_, text in rows], request_kind="match_notes_common")
        if len(vectors) != len(rows):
            raise ValueError("embedding result count does not match note count")
    except Exception as error:
        logger.warning("agent.matching.common.failed error_type=%s", type(error).__name__)
        return people
    notes: dict[str, list[tuple[str, str, list[float]]]] = {ref: [] for ref in people}
    for (ref, note_id, kind, _), vector in zip(rows, vectors, strict=True):
        notes[ref].append((note_id, kind, vector))
    common = common_note_ids(notes)
    return {
        ref: replace(person, lines=tuple(replace(note, common=True) if note.note_id in common[ref] else note for note in person.lines)) if common[ref] else person
        for ref, person in people.items()
    }


def _nameless(text: str, name: str) -> str:
    """The note without the person's name, so two notes are compared on what they say."""
    return re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "They", text) if name else text


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm and len(a) == len(b) else 0.0


__all__ = ["COMMON_SHARE", "MIN_GROUP", "SAME_MEANING", "common_note_ids", "mark_common"]
