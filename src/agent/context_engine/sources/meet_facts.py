"""What Omi still needs to know before it can set up a meet, given as a goal, never a form."""

from __future__ import annotations

from typing import Any

from agent.matching.readiness import MEET_FACT_GOALS, match_readiness

MEET_FACTS_SOURCE_TYPE = "meet_facts"
# Only once the basics of their vibe are in: before that the chat has better things to do.
_FROM_MILESTONES = {"basics", "ready_to_match", "deep"}


def meet_facts_sources(user_id: str | None) -> list[dict[str, Any]]:
    if not user_id:
        return []
    readiness = match_readiness(user_id)
    if readiness.milestone not in _FROM_MILESTONES or not readiness.facts_missing:
        return []
    return [
        {
            "source_type": MEET_FACTS_SOURCE_TYPE,
            "title": "Before you can set up a meet",
            "content": "\n".join(
                [
                    "To introduce this user to someone nearby you still need, in plain facts:",
                    *(f"- {MEET_FACT_GOALS[fact_id]}" for fact_id in readiness.facts_missing),
                    "Learn these the way a friend would, one at a time, only when the moment is open: "
                    "when they mention plans, food, their area or a free evening. Never as a list, never "
                    "two in one reply, never when they are upset or asked for no questions.",
                ]
            ),
            "metadata": {"missing": list(readiness.facts_missing), "milestone": readiness.milestone},
        }
    ]


__all__ = ["MEET_FACTS_SOURCE_TYPE", "meet_facts_sources"]
