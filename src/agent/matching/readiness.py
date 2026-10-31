"""Is this user known well enough to be matched, and what is still missing.

Two things must be true. The vibe card has reached "ready_to_match" (every basic area clear, at
least three deeper ones). And the plain facts a first meet needs are known from memories: where
they live and when they are free; what they eat and what they like to spend are good to have.
Nothing here asks the user anything: the companion gets the missing items as a goal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.memory_engine.memories.ranking import text_relevance
from agent.shared.vibe import VIBE_AREA_IDS, vibe_progress

# (id, what Omi needs to know, required before match day). The text doubles as the search for a
# memory that answers it, so it is written the way such a memory reads.
MEET_FACTS: tuple[tuple[str, str, bool], ...] = (
    ("area", "where they live: their area, locality or neighbourhood in the city", True),
    ("free_time", "when they are free to meet: evenings, weekends, days off, their routine", True),
    ("food", "what they eat or avoid: vegetarian, non-veg, drinks, food they love", False),
    ("budget", "how they like to go out: cheap chai or fancy places, how much they spend", False),
)
MEET_FACT_GOALS = {fact_id: goal for fact_id, goal, _ in MEET_FACTS}
# A memory this related to the question counts as answering it. Measured on samples: a real
# answer ("lives in Baner", "free on weekends") scores 0.17 to 0.33, an unrelated memory under 0.1.
_FACT_RELEVANCE_FLOOR = 0.12
_READY_MILESTONES = {"ready_to_match", "deep"}


@dataclass(frozen=True)
class MatchReadiness:
    ready: bool
    milestone: str
    clear_areas: tuple[str, ...]
    mentioned_areas: tuple[str, ...]
    missing_areas: tuple[str, ...]
    facts_known: dict[str, str] = field(default_factory=dict)
    facts_missing: tuple[str, ...] = ()
    private_allowed: bool = False
    # Plain words for the operator view and the user's own page.
    blockers: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "milestone": self.milestone,
            "areas": {"clear": list(self.clear_areas), "mentioned": list(self.mentioned_areas), "missing": list(self.missing_areas)},
            "facts": {"known": dict(self.facts_known), "missing": list(self.facts_missing)},
            "private_allowed": self.private_allowed,
            "blockers": list(self.blockers),
        }


def match_readiness(user_id: str) -> MatchReadiness:
    from storage import get_user_profile, get_vibe_card, list_agent_memories, private_matching_allowed

    card = get_vibe_card(user_id)
    return readiness_from(
        card["areas"],
        [m for m in list_agent_memories(user_id) if m.get("status") == "active"],
        get_user_profile(user_id) or {},
        private_allowed=private_matching_allowed(card),
    )


def readiness_from(
    areas: dict[str, Any],
    memories: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    private_allowed: bool = False,
) -> MatchReadiness:
    progress = vibe_progress(areas)
    known = set(progress.known)
    facts_known: dict[str, str] = {}
    for fact_id, goal, _ in MEET_FACTS:
        answer = _fact_from_memories(goal, memories)
        if answer is None and fact_id == "area" and profile.get("city"):
            answer = f"city: {profile['city']} (area not known)"
        if answer is not None:
            facts_known[fact_id] = answer
    facts_missing = tuple(fact_id for fact_id, _, _ in MEET_FACTS if fact_id not in facts_known)
    required_missing = tuple(fact_id for fact_id, _, required in MEET_FACTS if required and fact_id not in facts_known)
    blockers: list[str] = []
    if progress.milestone not in _READY_MILESTONES:
        blockers.append(f"vibe card is at '{progress.milestone}', needs 'ready_to_match'")
    if required_missing:
        blockers.append("not known yet: " + ", ".join(fact_id.replace("_", " ") for fact_id in required_missing))
    return MatchReadiness(
        ready=not blockers,
        milestone=progress.milestone,
        clear_areas=progress.clear,
        mentioned_areas=progress.mentioned,
        missing_areas=tuple(area_id for area_id in VIBE_AREA_IDS if area_id not in known),
        facts_known=facts_known,
        facts_missing=facts_missing,
        private_allowed=private_allowed,
        blockers=tuple(blockers),
    )


def _fact_from_memories(goal: str, memories: list[dict[str, Any]]) -> str | None:
    """The statement of the memory most related to the goal, when related enough."""
    best, best_score = None, 0.0
    for memory in memories:
        score = text_relevance(goal, str(memory.get("statement") or memory.get("value") or ""))
        if score > best_score:
            best, best_score = memory, score
    if best is None or best_score < _FACT_RELEVANCE_FLOOR:
        return None
    return str(best.get("statement") or best.get("value") or "")[:200] or None


__all__ = ["MEET_FACTS", "MEET_FACT_GOALS", "MatchReadiness", "match_readiness", "readiness_from"]
