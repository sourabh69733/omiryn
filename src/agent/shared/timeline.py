"""Turns message timestamps into plain time facts the companion can rely on.

Code computes every date and gap here; the model only receives the results, so it never
has to guess how long the user was away or what time it is for them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .clock import utc_now

_FALLBACK_TIMEZONE = "UTC"


def default_timezone_name() -> str:
    return os.getenv("AGENT_DEFAULT_TIMEZONE", "Asia/Kolkata").strip() or _FALLBACK_TIMEZONE


def valid_timezone_name(name: str | None) -> str | None:
    """Return the IANA name when it is a real timezone, otherwise None."""
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > 64:
        return None
    try:
        ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return cleaned


def user_zone(timezone_name: str | None) -> ZoneInfo:
    """The user's timezone, falling back to AGENT_DEFAULT_TIMEZONE and then UTC."""
    name = valid_timezone_name(timezone_name) or valid_timezone_name(default_timezone_name())
    return ZoneInfo(name or _FALLBACK_TIMEZONE)


def session_gap() -> timedelta:
    """Silence after which the next message starts a new session (AGENT_SESSION_GAP_HOURS)."""
    try:
        hours = float(os.getenv("AGENT_SESSION_GAP_HOURS", "6"))
    except ValueError:
        hours = 6.0
    return timedelta(hours=max(0.1, hours))


def message_time(message: dict[str, Any]) -> datetime | None:
    return parse_time(message.get("created_at"))


def parse_time(value: Any) -> datetime | None:
    """Parse a timezone-aware ISO-8601 string; naive or invalid values give None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def humanize_gap(gap: timedelta) -> str:
    """Describe a duration the way a person would say it, e.g. '3 hours' or '2 weeks'."""
    seconds = max(0, int(gap.total_seconds()))
    for unit_seconds, unit in (
        (365 * 86_400, "year"),
        (30 * 86_400, "month"),
        (7 * 86_400, "week"),
        (86_400, "day"),
        (3_600, "hour"),
        (60, "minute"),
    ):
        if seconds >= unit_seconds:
            count = seconds // unit_seconds
            return f"{count} {unit}{'' if count == 1 else 's'}"
    return "less than a minute"


def day_part(local: datetime) -> str:
    hour = local.hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    if 21 <= hour or hour < 1:
        return "night"
    return "late night"


@dataclass(frozen=True)
class ConversationTime:
    """What the companion should know about time for one reply."""

    timezone: str
    now_local: datetime
    last_user_message_local: datetime | None
    gap_since_last_user_message: timedelta | None
    new_session: bool

    def profile_fields(self) -> dict[str, Any]:
        """Fields merged into the user profile read by the behavior prompt."""
        fields: dict[str, Any] = {
            "timezone": self.timezone,
            "current_date": self.now_local.strftime("%Y-%m-%d"),
            "current_time": self.now_local.strftime("%H:%M"),
            "current_weekday": self.now_local.strftime("%A"),
            "current_day_part": day_part(self.now_local),
            "current_local_label": _local_label(self.now_local, with_year=True),
            "new_session": self.new_session,
        }
        if self.last_user_message_local and self.gap_since_last_user_message is not None:
            fields["last_user_message_label"] = _local_label(self.last_user_message_local)
            fields["last_user_message_ago"] = humanize_gap(self.gap_since_last_user_message)
        return fields


def conversation_time(
    messages: list[dict[str, Any]],
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> ConversationTime:
    """Summarize the current time and the gap since the user last wrote in this chat."""
    zone = user_zone(timezone_name)
    current = now or utc_now()
    last_user_at = next(
        (
            sent
            for message in reversed(messages)
            if message.get("role") == "user" and (sent := message_time(message))
        ),
        None,
    )
    gap = max(current - last_user_at, timedelta(0)) if last_user_at else None
    return ConversationTime(
        timezone=zone.key,
        now_local=current.astimezone(zone),
        last_user_message_local=last_user_at.astimezone(zone) if last_user_at else None,
        gap_since_last_user_message=gap,
        new_session=gap is not None and gap >= session_gap(),
    )


def current_session_start(messages: list[dict[str, Any]]) -> int:
    """Index of the first message after the last silence of at least the session gap."""
    start = 0
    previous_sent: datetime | None = None
    for index, message in enumerate(messages):
        sent = message_time(message)
        if sent is None:
            continue
        if previous_sent is not None and sent - previous_sent >= session_gap():
            start = index
        previous_sent = sent
    return start


def day_notes(
    messages: list[dict[str, Any]],
    timezone_name: str | None = None,
) -> list[str | None]:
    """One note per message: a day anchor on selected user messages, otherwise None.

    The first dated user message gets its day, e.g. "(Mon 14 Sep)", so older lines are not
    read as today. Later user messages get one only when the day changes, or after a long
    silence, e.g. "(Wed 16 Sep, 2 days later)". Assistant messages never carry notes, so the
    model does not learn to write them.
    """
    zone = user_zone(timezone_name)
    notes: list[str | None] = []
    anchored = False
    previous_sent: datetime | None = None
    for message in messages:
        sent = message_time(message)
        note = None
        if message.get("role") == "user" and sent is not None:
            local = sent.astimezone(zone)
            label = f"{local.strftime('%a')} {local.day} {local.strftime('%b')}"
            gap = sent - previous_sent if previous_sent else None
            if gap is not None and gap >= session_gap():
                note = f"({label}, {humanize_gap(gap)} later)"
            elif not anchored or (
                previous_sent is not None and previous_sent.astimezone(zone).date() != local.date()
            ):
                note = f"({label})"
            anchored = True
        notes.append(note)
        if sent is not None:
            previous_sent = sent
    return notes


def date_label(local: datetime) -> str:
    """Date with weekday, such as 'Sat 12 Sep 2026'."""
    return f"{local.strftime('%a')} {local.day} {local.strftime('%b')} {local.year}"


def relative_day(day: date, today: date) -> str:
    """How far a day is from today, as a person would say it: 'tomorrow', 'in 2 days', '3 weeks ago'."""
    delta = (day - today).days
    named = {0: "today", 1: "tomorrow", -1: "yesterday"}
    if delta in named:
        return named[delta]
    size = abs(delta)
    if size < 7:
        # Within a week the weekday is how people say it: "this Friday", "on Sunday".
        weekday = day.strftime("%A")
        return f"this {weekday}, in {size} days" if delta > 0 else f"on {weekday}, {size} days ago"
    if size < 14:
        amount = f"{size} days"
    elif size < 60:
        amount = f"{size // 7} weeks"
    else:
        months = size // 30
        amount = f"{months} month{'' if months == 1 else 's'}"
    return f"in {amount}" if delta > 0 else f"{amount} ago"


def _local_label(local: datetime, *, with_year: bool = False) -> str:
    # Built by hand so the output does not depend on the server's locale.
    time_text = local.strftime("%I:%M %p").lstrip("0").lower()
    date_text = f"{local.strftime('%A')} {local.day} {local.strftime('%b')}"
    if with_year:
        date_text += f" {local.year}"
    return f"{date_text}, {time_text}"


__all__ = [
    "ConversationTime",
    "conversation_time",
    "current_session_start",
    "date_label",
    "day_part",
    "default_timezone_name",
    "day_notes",
    "humanize_gap",
    "message_time",
    "parse_time",
    "relative_day",
    "session_gap",
    "user_zone",
    "valid_timezone_name",
]
