"""The user's friend vibe: what the companion understands about who they'd get along with.

Background cognition writes one short line per area from what the user actually said. Code only
validates the shape and counts filled areas into milestones; it never decides what to ask.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# (id, stage, goal). The goal tells the models what the area means; it is not a question to ask.
VIBE_AREAS: tuple[tuple[str, str, str], ...] = (
    ("friend_wish", "basics", "what they want from a friend and what a good friendship feels like to them"),
    ("humor", "basics", "what makes them laugh and how they joke"),
    ("social_energy", "basics", "quiet or loud, small group or crowd, planned or spontaneous"),
    ("interests", "basics", "what they love doing or could talk about for hours"),
    ("daily_life", "basics", "what fills their days (study, work, routine) and when they have free time"),
    ("values", "deeper", "beliefs and views they care about: god, caste, politics, work, money"),
    ("stories", "deeper", "experiences that shaped them, or stories they relate to"),
    ("accepts", "deeper", "differences in a friend they are fine with"),
    ("deal_breakers", "deeper", "what they cannot stand in a friend"),
    ("conflict", "deeper", "how they handle disagreement or hurt"),
    ("keeping_in_touch", "deeper", "how they like to stay in touch and how often"),
)
VIBE_AREA_IDS = tuple(area_id for area_id, _, _ in VIBE_AREAS)
BASIC_AREA_IDS = tuple(area_id for area_id, stage, _ in VIBE_AREAS if stage == "basics")
DEEPER_AREA_IDS = tuple(area_id for area_id, stage, _ in VIBE_AREAS if stage == "deeper")
VIBE_AREA_GOALS = {area_id: goal for area_id, _, goal in VIBE_AREAS}
MAX_VIBE_LINE_CHARS = 220
MAX_VIBE_UPDATES = 4

# How a vibe line is written; shared by the live background prompt and the backfill.
VIBE_LINE_RULES = """- A line is one or two plain sentences in the user's own terms, folding in the current line:
  "<what they said, specific>". Write what they showed, not a label: not "funny", but what makes
  them laugh.
- Only what the user said or plainly showed about themselves. Never guess from one word, never from
  the companion's messages, and never fill an area just because it is empty."""

# In order. "ready_to_match" is what matching will wait for.
VIBE_MILESTONES = ("starting", "first_impressions", "basics", "ready_to_match", "deep")
VIBE_MILESTONE_MEANINGS = {
    "starting": "just getting to know them",
    "first_impressions": "a first sense of their vibe",
    "basics": "the basics of what they want in friends",
    "ready_to_match": "enough to start looking for friends they'd get along with",
    "deep": "a deep understanding of their friend vibe",
}


@dataclass(frozen=True)
class VibeProgress:
    milestone: str
    known: tuple[str, ...]
    open: tuple[str, ...]
    basics_known: int
    deeper_known: int

    @property
    def next_milestone(self) -> str | None:
        position = VIBE_MILESTONES.index(self.milestone)
        return VIBE_MILESTONES[position + 1] if position + 1 < len(VIBE_MILESTONES) else None


def vibe_progress(card: dict[str, str] | None) -> VibeProgress:
    card = card or {}
    known = tuple(area_id for area_id in VIBE_AREA_IDS if card.get(area_id))
    basics = sum(area_id in known for area_id in BASIC_AREA_IDS)
    deeper = sum(area_id in known for area_id in DEEPER_AREA_IDS)
    if len(known) == len(VIBE_AREA_IDS):
        milestone = "deep"
    elif basics == len(BASIC_AREA_IDS) and deeper >= 3:
        milestone = "ready_to_match"
    elif basics == len(BASIC_AREA_IDS):
        milestone = "basics"
    elif len(known) >= 2:
        milestone = "first_impressions"
    else:
        milestone = "starting"
    return VibeProgress(
        milestone=milestone,
        known=known,
        open=tuple(area_id for area_id in VIBE_AREA_IDS if area_id not in known),
        basics_known=basics,
        deeper_known=deeper,
    )


def validate_vibe_updates(raw: Any, *, max_updates: int = MAX_VIBE_UPDATES) -> dict[str, str]:
    """Area lines the model rewrote. Unknown areas, empty lines and extras are dropped."""
    if not isinstance(raw, dict):
        return {}
    updates: dict[str, str] = {}
    for area_id, text in raw.items():
        if area_id not in VIBE_AREA_GOALS or not isinstance(text, str):
            continue
        line = " ".join(text.split())
        if not line:
            continue
        if len(line) > MAX_VIBE_LINE_CHARS:
            line = line[:MAX_VIBE_LINE_CHARS].rsplit(" ", 1)[0]
        updates[area_id] = line
        if len(updates) >= max_updates:
            break
    return updates


def merge_vibe(card: dict[str, str] | None, updates: dict[str, str]) -> dict[str, str]:
    merged = {area_id: text for area_id, text in (card or {}).items() if area_id in VIBE_AREA_GOALS}
    merged.update(updates)
    return {area_id: merged[area_id] for area_id in VIBE_AREA_IDS if merged.get(area_id)}


__all__ = [
    "BASIC_AREA_IDS",
    "DEEPER_AREA_IDS",
    "MAX_VIBE_LINE_CHARS",
    "VIBE_AREAS",
    "VIBE_AREA_GOALS",
    "VIBE_AREA_IDS",
    "VIBE_LINE_RULES",
    "VIBE_MILESTONES",
    "VIBE_MILESTONE_MEANINGS",
    "VibeProgress",
    "merge_vibe",
    "validate_vibe_updates",
    "vibe_progress",
]
