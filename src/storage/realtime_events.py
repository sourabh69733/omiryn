"""The shared log of realtime events, read by every other instance and pushed to its sockets."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text

from .database import ENGINE
from .schema import realtime_events

# The Postgres channel an insert notifies; listeners wake and read the new rows.
NOTIFY_CHANNEL = "omiryn_realtime"


def append_realtime_event(instance_id: str, event: dict[str, Any]) -> int:
    """Store one event for the other instances; returns its row id."""
    with ENGINE.begin() as connection:
        row_id = connection.execute(
            realtime_events.insert().values(instance_id=instance_id, event_json=event).returning(realtime_events.c.id)
        ).scalar_one()
        if connection.dialect.name == "postgresql":
            connection.execute(text(f"NOTIFY {NOTIFY_CHANNEL}"))
    return int(row_id)


def latest_realtime_event_id() -> int:
    """Where a reader starts: events before it came while this instance was not listening."""
    with ENGINE.begin() as connection:
        return int(connection.execute(select(func.max(realtime_events.c.id))).scalar() or 0)


def realtime_events_after(after_id: int, *, exclude_instance: str, limit: int = 200) -> list[tuple[int, dict[str, Any]]]:
    """Events other instances stored after `after_id`, oldest first."""
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(realtime_events.c.id, realtime_events.c.event_json)
            .where(realtime_events.c.id > after_id, realtime_events.c.instance_id != exclude_instance)
            .order_by(realtime_events.c.id.asc())
            .limit(limit)
        ).all()
    return [(int(row_id), dict(event)) for row_id, event in rows if isinstance(event, dict)]


__all__ = ["NOTIFY_CHANNEL", "append_realtime_event", "latest_realtime_event_id", "realtime_events_after"]
