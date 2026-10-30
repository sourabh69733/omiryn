"""Carries realtime events between server instances.

A socket lives on one instance, but a reply, nudge or story part may be saved on another. Every
instance appends the events it publishes to `realtime_events`; every instance reads the rows the
others appended and pushes them to its own sockets. On Postgres an insert sends NOTIFY, so the
reader wakes at once; otherwise, and as a safety net, it polls.

Off with REALTIME_FANOUT=off (one instance, no table writes).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from agent.shared.clock import utc_now

from .contracts import RealtimeEvent

if TYPE_CHECKING:  # pragma: no cover
    from .hub import InMemoryRealtimeHub

logger = logging.getLogger(__name__)

# With LISTEN the poll is only a safety net; without it, it is the transport.
POLL_SECONDS_WITH_LISTEN = 15.0
POLL_SECONDS_WITHOUT_LISTEN = 1.0
_LISTEN_RETRY_SECONDS = 5.0


def fanout_enabled() -> bool:
    return os.getenv("REALTIME_FANOUT", "on").strip().lower() not in {"off", "false", "0"}


class RealtimeFanout:
    def __init__(self, hub: "InMemoryRealtimeHub", *, poll_seconds: float | None = None) -> None:
        self._hub = hub
        self._poll_seconds = poll_seconds
        self._wake = asyncio.Event()
        self._last_id: int | None = None
        self._tasks: list[asyncio.Task[None]] = []

    async def publish(self, event: RealtimeEvent) -> None:
        """Store the event for the other instances; best effort, local delivery already happened."""
        if not fanout_enabled():
            return
        from storage import append_realtime_event

        try:
            await asyncio.to_thread(append_realtime_event, self._hub.instance_id, event.as_dict())
        except Exception:
            logger.warning("realtime.fanout.publish_failed instance=%s", self._hub.instance_id, exc_info=True)

    def start(self) -> None:
        if self._tasks or not fanout_enabled():
            return
        self._tasks.append(asyncio.create_task(self._poll_loop(), name="realtime-fanout"))
        if _postgres_dsn():
            self._tasks.append(asyncio.create_task(self._listen_loop(), name="realtime-fanout-listen"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def drain(self) -> int:
        """Push every event other instances stored since the last read; returns how many."""
        from storage import latest_realtime_event_id, realtime_events_after

        if self._last_id is None:
            # Events from before this instance listened belong to sockets that were elsewhere.
            self._last_id = await asyncio.to_thread(latest_realtime_event_id)
            return 0
        delivered = 0
        while True:
            rows = await asyncio.to_thread(realtime_events_after, self._last_id, exclude_instance=self._hub.instance_id)
            for row_id, raw in rows:
                self._last_id = row_id
                event = _event_from_dict(raw)
                if event is not None:
                    await self._hub.publish_local(event)
                    delivered += 1
            if len(rows) < 200:
                return delivered

    async def _poll_loop(self) -> None:
        interval = self._poll_seconds or (POLL_SECONDS_WITH_LISTEN if _postgres_dsn() else POLL_SECONDS_WITHOUT_LISTEN)
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                await self.drain()
            except Exception:
                logger.warning("realtime.fanout.read_failed", exc_info=True)

    async def _listen_loop(self) -> None:
        """LISTEN on Postgres; every NOTIFY wakes the reader. Reconnects after an error."""
        import psycopg

        from storage.realtime_events import NOTIFY_CHANNEL

        while True:
            try:
                async with await psycopg.AsyncConnection.connect(_postgres_dsn(), autocommit=True) as connection:
                    await connection.execute(f"LISTEN {NOTIFY_CHANNEL}")
                    logger.info("realtime.fanout.listening instance=%s", self._hub.instance_id)
                    async for _notify in connection.notifies():
                        self._wake.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("realtime.fanout.listen_failed; retrying", exc_info=True)
                await asyncio.sleep(_LISTEN_RETRY_SECONDS)


def _postgres_dsn() -> str | None:
    from storage.database import database_url

    url = database_url()
    if not url.startswith("postgresql"):
        return None
    return "postgresql://" + url.split("://", 1)[1]


def _event_from_dict(raw: dict[str, Any]) -> RealtimeEvent | None:
    try:
        return RealtimeEvent(
            type=str(raw["type"]),
            scope=raw["scope"],
            scope_id=str(raw["scope_id"]),
            payload=dict(raw.get("payload") or {}),
            sequence=raw.get("sequence"),
            event_id=str(raw.get("event_id") or ""),
            occurred_at=str(raw.get("occurred_at") or utc_now().isoformat()),
        )
    except (KeyError, TypeError, ValueError):
        logger.warning("realtime.fanout.bad_event")
        return None


__all__ = ["RealtimeFanout", "fanout_enabled"]
