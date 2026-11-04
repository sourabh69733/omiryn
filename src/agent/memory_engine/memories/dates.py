"""Works out when the things a user told Omi happen: one-off events and repeating ones.

Code computes every date here. The background model only records that something repeats; the reply
model only reads the dates that come out.

A repeating memory stores `repeats` with its own day: `yearly:03-12`, `monthly:5` or `weekly:tue,thu`.
The day is what the user said, so it needs no date arithmetic from the model; given a nearest date to
work out instead, it often wrote today's. occurred_at stays empty on these.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta, tzinfo
from typing import Any

from agent.shared.timeline import parse_time

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# Long enough to hold the next time of anything yearly, Feb 29 included.
_NEXT_SEARCH_DAYS = 366


def normalize_repeats(value: Any) -> str | None:
    """The stored form of `repeats`, or None when no real day can come from it."""
    if not isinstance(value, str):
        return None
    every, _, day = value.strip().lower().partition(":")
    if every == "yearly":
        return f"yearly:{day}" if _year_day(day) else None
    if every == "monthly":
        return f"monthly:{int(day)}" if day.isdigit() and 1 <= int(day) <= 31 else None
    if every != "weekly":
        return None
    chosen = {name.strip()[:3] for name in day.split(",")}
    # All seven is a daily habit, not something a calendar can usefully say.
    if not chosen <= set(WEEKDAYS) or not 1 <= len(chosen) < len(WEEKDAYS):
        return None
    return "weekly:" + ",".join(name for name in WEEKDAYS if name in chosen)


def occurrences_between(memory: dict[str, Any], first: date, last: date, zone: tzinfo) -> list[date]:
    """Every day from first to last, both included, that this memory happens on."""
    every, _, day = str(memory.get("repeats") or "").partition(":")
    if not every:
        anchor = _local_day(memory.get("occurred_at"), zone)
        return [anchor] if anchor and first <= anchor <= last else []
    start, end = _repeat_bounds(memory, every, first, last, zone)
    if every == "yearly" and (month_day := _year_day(day)):
        found = [_day_in_month(year, *month_day) for year in range(start.year, end.year + 1)]
    elif every == "monthly" and day.isdigit():
        found = [_day_in_month(year, month, int(day)) for year, month in _months(start, end)]
    elif every == "weekly":
        weekdays = {WEEKDAYS.index(name) for name in day.split(",") if name in WEEKDAYS}
        span = (end - start).days + 1
        found = [moment for moment in (start + timedelta(days=n) for n in range(span)) if moment.weekday() in weekdays]
    else:
        found = []
    return [moment for moment in found if start <= moment <= end]


def next_occurrence(memory: dict[str, Any], today: date, zone: tzinfo) -> date | None:
    """The next day a repeating memory happens, today included."""
    found = occurrences_between(memory, today, today + timedelta(days=_NEXT_SEARCH_DAYS), zone)
    return found[0] if found else None


def repeats_label(repeats: Any) -> str:
    """'every year', 'every month', 'every Tue, Thu'; empty when it does not repeat."""
    every, _, day = str(repeats or "").partition(":")
    if every == "yearly":
        return "every year"
    if every == "monthly":
        return "every month"
    if every == "weekly":
        return "every " + ", ".join(name.title() for name in day.split(","))
    return ""


def period_range(period: str, today: date) -> tuple[date, date] | None:
    """The days a named period covers, weeks starting on Monday. None for an unknown name."""
    monday = today - timedelta(days=today.weekday())
    this_month_start = today.replace(day=1)
    next_month_start = _day_in_month(*_month_after(today.year, today.month), 1)
    last_month_end = this_month_start - timedelta(days=1)
    ranges = {
        "yesterday": (today - timedelta(days=1),) * 2,
        "today": (today, today),
        "tomorrow": (today + timedelta(days=1),) * 2,
        "last_week": (monday - timedelta(days=7), monday - timedelta(days=1)),
        "this_week": (monday, monday + timedelta(days=6)),
        "next_week": (monday + timedelta(days=7), monday + timedelta(days=13)),
        "last_month": (last_month_end.replace(day=1), last_month_end),
        "this_month": (this_month_start, next_month_start - timedelta(days=1)),
        "next_month": (next_month_start, _last_day_of_month(next_month_start)),
    }
    return ranges.get(period)


PERIODS = (
    "yesterday",
    "today",
    "tomorrow",
    "last_week",
    "this_week",
    "next_week",
    "last_month",
    "this_month",
    "next_month",
)


def _repeat_bounds(
    memory: dict[str, Any], every: str, first: date, last: date, zone: tzinfo
) -> tuple[date, date]:
    """A repeating thing never runs past its end. A birthday was true before the user said it, but
    a weekly gym or monthly rent is only known from when it started or was first told."""
    start, end = first, last
    if until := _local_day(memory.get("valid_until"), zone):
        end = min(end, until)
    begun = _local_day(memory.get("valid_from"), zone)
    if begun is None and every != "yearly":
        begun = _local_day(memory.get("created_at"), zone)
    if begun:
        start = max(start, begun)
    return start, end


def _year_day(text: str) -> tuple[int, int] | None:
    """(month, day) from '03-12'; 02-29 is allowed. None when it is not a real day."""
    month, _, day = text.partition("-")
    if not (month.isdigit() and day.isdigit()):
        return None
    try:
        date(2024, int(month), int(day))
    except ValueError:
        return None
    return int(month), int(day)


def _local_day(value: Any, zone: tzinfo) -> date | None:
    moment = parse_time(value)
    return moment.astimezone(zone).date() if moment else None


def _day_in_month(year: int, month: int, day: int) -> date:
    """That day of the month, or the month's last day when it is shorter (Feb 29, the 31st)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _last_day_of_month(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _month_after(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _months(start: date, end: date) -> list[tuple[int, int]]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        year, month = _month_after(year, month)
    return months


__all__ = [
    "PERIODS",
    "WEEKDAYS",
    "next_occurrence",
    "normalize_repeats",
    "occurrences_between",
    "period_range",
    "repeats_label",
]
