"""Supplies the companion's private goal: understand the user's friend vibe."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.context_engine.contracts.models import MatchingUnderstanding
from agent.memory_engine.memories.vibe import VIBE_AREA_GOALS, VIBE_MILESTONE_MEANINGS
from agent.shared.clock import utc_now

# How long a newly reached milestone stays news the companion may mention.
MILESTONE_NEWS_WINDOW = timedelta(hours=24)


def matching_understanding_prompt(
    progress: MatchingUnderstanding,
    *,
    now: datetime | None = None,
) -> str:
    # Rules first: a long card is trimmed from the end, never the rules.
    lines = [
        "Your purpose (private): over many chats, understand who this user would truly get along "
        "with as a friend, so Omiryn can find those friends. You learn it by being good company, "
        "never by interviewing.",
        "This is a goal, not a checklist. The user's mood, request and current topic always come "
        "first. When the moment is open, you may steer toward something not understood yet in "
        "your own way: an opinion, a story, a playful this-or-that, or one curious question. "
        "Never two of these areas in one reply, never right after they dodged one. Do not name "
        "these areas or show progress numbers. If asked what you know about them, say it plainly.",
    ]
    news = _milestone_news(progress, now or utc_now())
    lines.append(
        news or f"Where you are: {VIBE_MILESTONE_MEANINGS.get(progress.level, progress.level)}."
    )
    if progress.unexplored_dimensions:
        lines.append("Not understood yet (earlier ones matter more):")
        lines.extend(
            f"- {area_id.replace('_', ' ')}: {VIBE_AREA_GOALS.get(area_id, '')}"
            for area_id in progress.unexplored_dimensions
        )
    lines.append("What you understand so far:")
    if progress.area_lines:
        lines.extend(
            f"- {area_id.replace('_', ' ')}{' (said on one day only)' if strength == 'mentioned' else ''}: {text}"
            for area_id, text, strength in progress.area_lines
        )
    else:
        lines.append("- nothing yet")
    return "\n".join(lines)


def _milestone_news(progress: MatchingUnderstanding, now: datetime) -> str | None:
    reached_at = progress.milestone_reached_at
    if reached_at is None:
        return None
    if reached_at.tzinfo is None:
        reached_at = reached_at.replace(tzinfo=timezone.utc)
    if now - reached_at > MILESTONE_NEWS_WINDOW:
        return None
    hours = max(0, int((now - reached_at).total_seconds() // 3600))
    when = "within the last hour" if hours == 0 else f"about {hours} hour{'s' if hours != 1 else ''} ago"
    return (
        f"New ({when}): you now have {VIBE_MILESTONE_MEANINGS.get(progress.level, progress.level)}. "
        "The app shows them this too. If you have not mentioned it in this chat and it fits the "
        "moment, you may tell them in your own words what it means for finding them friends; "
        "skip it when they are busy with something else."
    )
