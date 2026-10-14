"""Freshness of a current-focus memory, computed from its dates.

A focus is something the user is into for a while: studying a topic, preparing for an exam, a
project. Like in a human mind it stays fresh while they keep mentioning it, fades after weeks of
silence (kept, but not assumed to still be going) and is then archived (history only: not used in
replies, still on the Memories page). Only a new mention refreshes it. The model decides what is a
focus and what counts as a mention; code only measures time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from agent.shared.timeline import parse_time

FocusState = Literal["current", "fading", "archived"]

FRESH_FOR = timedelta(days=14)
ARCHIVED_AFTER = timedelta(days=45)


def last_mentioned(memory: dict[str, Any]) -> datetime | None:
    """When the user last talked about it: the newest proof or reinforcement."""
    moments = [parse_time(evidence.get("observed_at")) for evidence in memory.get("evidence") or []]
    moments.append(parse_time(memory.get("last_reinforced_at")))
    known = [moment for moment in moments if moment is not None]
    return max(known) if known else parse_time(memory.get("created_at"))


def focus_state(memory: dict[str, Any], now: datetime) -> FocusState | None:
    """None for a memory that is not a focus."""
    if not memory.get("focus"):
        return None
    mentioned = last_mentioned(memory)
    if mentioned is None:
        return "current"
    silence = now - mentioned
    if silence >= ARCHIVED_AFTER:
        return "archived"
    return "fading" if silence >= FRESH_FOR else "current"


__all__ = ["ARCHIVED_AFTER", "FRESH_FOR", "focus_state", "last_mentioned"]
