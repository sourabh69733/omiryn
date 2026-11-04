"""The user's dates around today, worked out in code, so "what do I have this week?" or "where did I
go last week?" has a true answer on any reply without reading the message for date words."""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from agent.memory_engine.memories.dates import repeats_label
from agent.memory_engine.memories.retrieval import memories_on_dates
from agent.shared.clock import utc_now
from agent.shared.timeline import clock_label, date_label, parse_time, relative_day, user_zone
from storage import get_user_timezone

from .memories import memory_sentence

CALENDAR_SOURCE_TYPE = "calendar"
CALENDAR_DAYS = 14
CALENDAR_LINES = 10
# Past events are few and only some matter; coming ones get the most room.
CALENDAR_PAST_LINES = 4


def calendar_sources(user_id: str | None, now: datetime | None = None) -> list[dict[str, Any]]:
    if not user_id:
        return []
    zone = user_zone(get_user_timezone(user_id))
    today = (now or utc_now()).astimezone(zone).date()
    past = _past_events(user_id, today, zone)
    room = CALENDAR_LINES - min(len(past), CALENDAR_PAST_LINES)
    coming = memories_on_dates(user_id, today, today + timedelta(days=CALENDAR_DAYS), zone, limit=room + 1)
    more = len(past) > CALENDAR_PAST_LINES or len(coming) > room
    entries = past[:CALENDAR_PAST_LINES][::-1] + coming[:room]
    if not entries:
        return []
    lines = [
        f"Dates they told you, from {CALENDAR_DAYS} days ago to {CALENDAR_DAYS} days ahead, worked out by "
        "code. Answer from this when they ask about a day, their week or what happened or is coming up; "
        "a day in this range that is not listed has nothing you know of. It is a calendar to read from, "
        "not a list to bring up.",
        *(dated_line(memory, day, today, zone) for day, memory in entries),
    ]
    if more:
        lines.append("More dates than these are saved: memories_by_date has the rest.")
    return [
        {
            "source_type": CALENDAR_SOURCE_TYPE,
            "title": "Their calendar",
            "content": "\n".join(lines),
            "metadata": {"memory_ids": [memory.get("id") for _, memory in entries]},
        }
    ]


def _past_events(user_id: str, today: date, zone: tzinfo) -> list[tuple[date, dict[str, Any]]]:
    """One-off events only, newest first: a weekly gym having happened says nothing."""
    entries = memories_on_dates(
        user_id, today - timedelta(days=CALENDAR_DAYS), today - timedelta(days=1), zone, limit=50
    )
    return [entry for entry in entries[::-1] if not entry[1].get("repeats")]


def dated_line(memory: dict[str, Any], day: date, today: date, zone: tzinfo) -> str:
    """'- Tue 10 Nov 2026 (this Tuesday, in 6 days), every Tue, Thu: Goes to the gym.'"""
    when = f"{date_label(day)} ({relative_day(day, today)})"
    if every := repeats_label(memory.get("repeats")):
        when += f", {every}"
    elif moment := parse_time(memory.get("occurred_at")):
        local = moment.astimezone(zone)
        # 12:00 is what the background model writes when no time of day was stated.
        if (local.hour, local.minute) != (12, 0):
            when += f", {clock_label(local)}"
    return f"- {when}: {memory_sentence(memory)}"


__all__ = ["CALENDAR_DAYS", "CALENDAR_LINES", "CALENDAR_SOURCE_TYPE", "calendar_sources", "dated_line"]
