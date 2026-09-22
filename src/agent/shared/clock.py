"""Single source of the current time for agent code, so tests can move the clock."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

_frozen_now: ContextVar[datetime | None] = ContextVar("agent_frozen_now", default=None)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time, or the frozen time inside `frozen_time`."""
    return _frozen_now.get() or datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


@contextmanager
def frozen_time(at: datetime) -> Iterator[None]:
    """Pin `utc_now()` to one instant, for tests and simulated time jumps."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("frozen_time requires a timezone-aware datetime")
    token = _frozen_now.set(at.astimezone(UTC))
    try:
        yield
    finally:
        _frozen_now.reset(token)


__all__ = ["frozen_time", "utc_now", "utc_now_iso"]
