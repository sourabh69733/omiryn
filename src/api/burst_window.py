"""How long Omi waits for more messages before it starts a reply.

People write a thought in several quick messages. A reply to the first one alone reads wrong, so
each message starts a wait for quiet; the longer the burst, the more likely another is coming, so
the wait grows with it. The max keeps someone who never stops from being ignored.
"""

from __future__ import annotations

import os
from datetime import datetime

# A flood from here on: answered as a whole, after a longer wait.
FLOOD_MESSAGES = 4
DEFAULT_QUIET_SECONDS = 1.5
SMALL_BURST_MAX_WAIT_SECONDS = 6.0
FLOOD_MAX_WAIT_SECONDS = 15.0


def base_quiet_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("CHAT_BURST_QUIET_SECONDS", DEFAULT_QUIET_SECONDS)))
    except ValueError:
        return DEFAULT_QUIET_SECONDS


def quiet_seconds(pending: int) -> float:
    """1 message: the base. 2-3: half as long again. A flood: twice as long."""
    base = base_quiet_seconds()
    if pending >= FLOOD_MESSAGES:
        return base * 2
    return base * 1.5 if pending > 1 else base


def max_wait_seconds(pending: int) -> float:
    return FLOOD_MAX_WAIT_SECONDS if pending >= FLOOD_MESSAGES else SMALL_BURST_MAX_WAIT_SECONDS


def seconds_left(pending: int, last_at: datetime, started_at: datetime, now: datetime) -> float:
    """How much longer to wait; zero or less means start the reply. `last_at` is the newest message
    or, on the web, the last sign the user is still typing."""
    return min(
        (last_at - now).total_seconds() + quiet_seconds(pending),
        (started_at - now).total_seconds() + max_wait_seconds(pending),
    )
