"""Projects the user's friend vibe card into the companion's private progress context."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.context_engine.contracts.models import MatchingDimensionProgress, MatchingUnderstanding
from agent.memory_engine.memories.vibe import (
    BASIC_AREA_IDS,
    DEEPER_AREA_IDS,
    VIBE_AREA_IDS,
    vibe_progress,
)

MATCHING_DIMENSIONS = VIBE_AREA_IDS


def build_matching_understanding(
    *,
    user_id: str | None,
    user_profile: dict[str, Any] | None = None,
) -> MatchingUnderstanding:
    if not user_id:
        return calculate_matching_understanding({})
    from storage.vibe_cards import get_vibe_card

    card = get_vibe_card(user_id)
    return calculate_matching_understanding(
        card["areas"],
        milestone_reached_at=card["milestone_reached_at"],
    )


def calculate_matching_understanding(
    areas: dict[str, str],
    *,
    milestone_reached_at: datetime | None = None,
) -> MatchingUnderstanding:
    progress = vibe_progress(areas)
    known = set(progress.known)
    dimensions = tuple(
        MatchingDimensionProgress(id=area_id, depth="clear" if area_id in known else "unknown")
        for area_id in VIBE_AREA_IDS
    )
    breadth = round(len(progress.known) / len(VIBE_AREA_IDS) * 100)
    return MatchingUnderstanding(
        level=progress.milestone,
        breadth_percent=breadth,
        depth_percent=breadth,
        foundation_covered=progress.basics_known,
        foundation_total=len(BASIC_AREA_IDS),
        dimensions=dimensions,
        known_dimensions=progress.known,
        # Basics first, so the companion's private hint leans toward them.
        unexplored_dimensions=tuple(
            area_id for area_id in (*BASIC_AREA_IDS, *DEEPER_AREA_IDS) if area_id not in known
        ),
        can_deepen_dimensions=(),
        area_lines=tuple((area_id, areas[area_id]) for area_id in progress.known),
        milestone_reached_at=milestone_reached_at if progress.milestone != "starting" else None,
    )
