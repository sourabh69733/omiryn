"""Story autoplay: after a story part, the next one follows on its own while the user listens.

Parts are durable jobs, so a restart loses nothing. Every few automatic parts end with a
check-in and wait for the user. Anything the user writes takes over: a "then?" continues the
story through a normal turn, anything else ends it. The job runner lives in
agent.proactive.story; this module only decides and schedules.
"""

from __future__ import annotations

import os
import random
from typing import Any

STORY_PART_JOB = "story_part"
# Every third automatic part ends with a check-in and waits for the user.
STORY_CHECK_IN_EVERY = 3


def story_autoplay_enabled() -> bool:
    return os.getenv("AGENT_STORY_AUTOPLAY", "true").strip().lower() not in {"0", "false", "off"}


def story_part_delay() -> float:
    """Seconds before the next part, like a person typing (AGENT_STORY_PART_MIN/MAX_SECONDS)."""
    low = _seconds("AGENT_STORY_PART_MIN_SECONDS", 30.0)
    high = max(low, _seconds("AGENT_STORY_PART_MAX_SECONDS", 90.0))
    return random.uniform(low, high)


def auto_parts_since_user(messages: list[dict[str, Any]]) -> int:
    """How many automatic story parts followed the user's last message."""
    parts = 0
    for message in reversed(messages):
        if message.get("role") == "user":
            break
        parts = max(parts, int(message.get("story_auto") or 0))
    return parts


def story_part_block_reason(messages: list[dict[str, Any]]) -> str | None:
    """Why no automatic part should follow now, or None when the story may go on."""
    if not messages:
        return "empty"
    last = messages[-1]
    if last.get("role") != "assistant" or not last.get("story"):
        return "not_telling_a_story"
    if last.get("story_end"):
        return "story_ended"
    if str(last.get("content") or "").rstrip().endswith("?"):
        return "waiting_for_user"
    if auto_parts_since_user(messages) >= STORY_CHECK_IN_EVERY:
        return "check_in_due"
    return None


def schedule_story_part(user_id: str, conversation_id: str) -> None:
    # Local import keeps this module importable without storage for pure policy checks.
    from agent.jobs.queue import schedule_job

    schedule_job(STORY_PART_JOB, user_id, conversation_id, delay_seconds=story_part_delay())


def _seconds(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, default)))
    except ValueError:
        return default


__all__ = [
    "STORY_CHECK_IN_EVERY",
    "STORY_PART_JOB",
    "auto_parts_since_user",
    "schedule_story_part",
    "story_autoplay_enabled",
    "story_part_block_reason",
    "story_part_delay",
]
