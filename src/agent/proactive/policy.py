"""Decides when the agent may open a conversation on its own, and about what.

The rules are deliberately conservative: reaching out uninvited is a risk to trust, so a
nudge needs recent silence, a small daily cap, and proof the user answered the last one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from agent.context_engine.conversation_engine.state.models import ConversationThread


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


def pick_thread(threads: list[ConversationThread]) -> ConversationThread | None:
    """Choose the open thread most worth reopening; never one the user is cool on."""
    candidates = [
        thread
        for thread in threads
        if thread.status == "open" and thread.next_angle and thread.user_interest != "low"
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
