"""Decides when the agent may open a conversation on its own, and about what.

The rules are deliberately conservative: reaching out uninvited is a risk to trust, so a
nudge needs recent silence, a small daily cap, and proof the user answered the last one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from agent.context_engine.threads.models import ConversationThread
from agent.shared.timeline import session_gap


def _default_min_silence() -> timedelta:
    """PROACTIVE_MIN_SILENCE_SECONDS shortens the wait for manual testing."""
    return timedelta(seconds=float(os.getenv("PROACTIVE_MIN_SILENCE_SECONDS", 30 * 60)))


@dataclass(frozen=True)
class ProactiveLimits:
    min_silence: timedelta = field(default_factory=_default_min_silence)
    window: timedelta = timedelta(hours=24)
    max_per_window: int = 2


def nudge_block_reason(
    messages: list[dict[str, Any]],
    now: datetime,
    limits: ProactiveLimits | None = None,
) -> str | None:
    """Return why a nudge must not be sent now, or None when it is allowed."""
    limits = limits or ProactiveLimits()
    if not any(message.get("role") == "user" for message in messages):
        return "no_user_message"
    last_sent = _parse_time(messages[-1].get("created_at"))
    if last_sent is None:
        return "unknown_last_message_time"
    if now - last_sent < limits.min_silence:
        return "recently_active"

    nudges = [
        (index, message)
        for index, message in enumerate(messages)
        if message.get("proactive") and message.get("role") == "assistant"
    ]
    if nudges:
        last_index = nudges[-1][0]
        # No pressure: stay quiet until the user has answered our last nudge.
        if not any(m.get("role") == "user" for m in messages[last_index + 1 :]):
            return "last_nudge_unanswered"
    recent = [
        message
        for _, message in nudges
        if (sent := _parse_time(message.get("created_at"))) and now - sent < limits.window
    ]
    if len(recent) >= limits.max_per_window:
        return "daily_limit"
    return None


def return_greeting_block_reason(
    messages: list[dict[str, Any]],
    now: datetime,
    limits: ProactiveLimits | None = None,
) -> str | None:
    """Why the agent must not greet a returning user now, or None when it may.

    A return is a new session (silence of at least AGENT_SESSION_GAP_HOURS). One greeting per
    return: if the last message is already ours, the user has not answered it yet.
    """
    limits = limits or ProactiveLimits()
    if not any(message.get("role") == "user" for message in messages):
        return "no_user_message"
    last_sent = _parse_time(messages[-1].get("created_at"))
    if last_sent is None:
        return "unknown_last_message_time"
    if now - last_sent < session_gap():
        return "no_long_gap"
    if messages[-1].get("proactive"):
        return "last_nudge_unanswered"
    recent = [
        message
        for message in messages
        if message.get("proactive")
        and message.get("role") == "assistant"
        and (sent := _parse_time(message.get("created_at")))
        and now - sent < limits.window
    ]
    if len(recent) >= limits.max_per_window:
        return "daily_limit"
    return None


# A promise this late is stale; raising it would feel odd rather than caring.
PROMISE_FOLLOW_UP_MAX_AGE = timedelta(days=14)


def due_promise(notes: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """The oldest active promise whose follow-up time has come, if any."""
    due = [
        (due_at, note)
        for note in notes
        if note.get("kind") == "promise"
        and (due_at := _parse_time(note.get("due_at")))
        and due_at <= now
        and now - due_at <= PROMISE_FOLLOW_UP_MAX_AGE
    ]
    return min(due, key=lambda item: item[0])[1] if due else None


# A plan is asked about a few hours after it happens. One with no time of day is stored at 12:00,
# so it is asked about the next morning instead of in the middle of that day.
EVENT_FOLLOW_UP_DELAY = timedelta(hours=3)
EVENT_NEXT_MORNING = time(9)
# Past this the question would feel late rather than caring.
EVENT_FOLLOW_UP_WINDOW = timedelta(days=3)
# At most one plan follow-up a day, across all chats.
EVENT_FOLLOW_UP_GAP = timedelta(hours=24)
# Local hours in which Omi may message a user who is away (Telegram); never at night.
REACH_OUT_HOURS = range(10, 21)


def event_follow_up_from(occurred_at: datetime, zone: ZoneInfo) -> datetime:
    local = occurred_at.astimezone(zone)
    if (local.hour, local.minute) == (12, 0):
        return datetime.combine(local.date() + timedelta(days=1), EVENT_NEXT_MORNING, tzinfo=zone)
    return occurred_at + EVENT_FOLLOW_UP_DELAY


def due_event(memories: list[dict[str, Any]], now: datetime, zone: ZoneInfo) -> dict[str, Any] | None:
    """The oldest plan the user told Omi about beforehand whose follow-up time has come, if any.

    Only plans said before they happened count; an event told afterwards was already talked
    about. Highly sensitive ones are left for the user to bring up.
    """
    if any(
        (asked := _parse_time(memory.get("followed_up_at"))) and now - asked < EVENT_FOLLOW_UP_GAP
        for memory in memories
    ):
        return None
    due = []
    for memory in memories:
        occurred = _parse_time(memory.get("occurred_at"))
        told = _parse_time(memory.get("created_at"))
        if (
            occurred is None
            or told is None
            or told >= occurred
            or memory.get("followed_up_at")
            or memory.get("status") != "active"
            or memory.get("sensitivity") == "highly_sensitive"
            or "reply_context" not in (memory.get("allowed_uses") or [])
        ):
            continue
        start = event_follow_up_from(occurred, zone)
        if start <= now <= start + EVENT_FOLLOW_UP_WINDOW:
            due.append((start, memory))
    return min(due, key=lambda item: item[0])[1] if due else None


def reach_out_hours(now: datetime, zone: ZoneInfo) -> bool:
    return now.astimezone(zone).hour in REACH_OUT_HOURS


def pick_thread(
    threads: list[ConversationThread],
    exclude_ids: set[str | None] | frozenset[str | None] = frozenset(),
) -> ConversationThread | None:
    """Choose the open thread most worth reopening.

    Skips threads the user is cool on and threads already nudged once, so the agent never
    circles back to the same topic.
    """
    candidates = [
        thread
        for thread in threads
        if thread.status == "open"
        and thread.next_angle
        and thread.user_interest != "low"
        and thread.id not in exclude_ids
    ]
    return max(candidates, key=lambda thread: thread.salience, default=None)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None
