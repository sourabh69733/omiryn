"""memories_by_date: the reply model looks up what the user told it about a stretch of days.

The model names the period; code works out the days, so "last week" is never its own arithmetic.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from agent.memory_engine.memories.dates import PERIODS, period_range
from agent.shared.clock import utc_now
from agent.shared.timeline import date_label, user_zone

from .registry import Tool, ToolContext, ToolResult, register_tool

MAX_RANGE_DAYS = 400
MAX_LINES = 20


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _range(arguments: dict[str, Any], today: date) -> tuple[date, date] | None:
    period = period_range(str(arguments.get("period") or "").strip().lower(), today)
    if period:
        return period
    start, end = _day(arguments.get("start_date")), _day(arguments.get("end_date"))
    if not (start or end):
        return None
    start, end = start or end, end or start
    start, end = min(start, end), max(start, end)
    return start, min(end, start + timedelta(days=MAX_RANGE_DAYS))


async def _run(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
    # Imported here: the context engine reads this package to know which tools are on.
    from agent.context_engine.sources.calendar import dated_line
    from agent.memory_engine.memories.retrieval import memories_on_dates
    from storage import get_user_timezone

    zone = user_zone(get_user_timezone(str(context.user_id)))
    today = utc_now().astimezone(zone).date()
    days = _range(arguments, today)
    if days is None:
        return ToolResult("Give a period, or a start_date and end_date as YYYY-MM-DD.", {"hits": 0})
    entries = memories_on_dates(str(context.user_id), days[0], days[1], zone, limit=MAX_LINES)
    span = f"{date_label(days[0])} to {date_label(days[1])}"
    trace = {"days": (days[1] - days[0]).days + 1, "hits": len(entries)}
    if not entries:
        return ToolResult(
            f"Nothing dated from {span}. This holds only dates they told you, so say you do not know of "
            "anything rather than guess; search_chats can find what was said in that time.",
            trace,
        )
    lines = "\n".join(dated_line(memory, day, today, zone) for day, memory in entries)
    return ToolResult(f"What they told you for {span}:\n{lines}", trace)


MEMORIES_BY_DATE = register_tool(
    Tool(
        name="memories_by_date",
        description=(
            "Look up what the user told you happens or happened on certain days: plans, events, birthdays, "
            "things that repeat. Use it when they ask about a day, week or month the context above does "
            "not cover. Name a period, or for anything else give start_date and end_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": list(PERIODS)},
                "start_date": {"type": "string", "description": "YYYY-MM-DD, when no period fits."},
                "end_date": {"type": "string", "description": "YYYY-MM-DD, when no period fits."},
            },
        },
        run=_run,
        enabled=lambda context: bool(context.user_id),
    )
)

__all__ = ["MEMORIES_BY_DATE"]
