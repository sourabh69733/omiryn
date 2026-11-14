"""Times every API call in memory and saves one summary per route each minute.

Requests never wait on the database for this: `record` only updates counters, and a background
task writes the finished minutes. Only the route template is kept (`/api/agent/conversations/{id}`),
never the real path, a user, or a body.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from storage import latency_bucket, save_request_stats
from storage.request_stats import REQUEST_LATENCY_BOUNDS_MS

logger = logging.getLogger(__name__)

FLUSH_SECONDS = 60


def app_release() -> str:
    """The deployed version: APP_RELEASE when set, else Cloud Run's revision name, else "dev"."""
    return os.getenv("APP_RELEASE") or os.getenv("K_REVISION") or "dev"


@dataclass
class _Bucket:
    count: int = 0
    server_errors: int = 0
    client_errors: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    histogram: list[int] = field(default_factory=lambda: [0] * (len(REQUEST_LATENCY_BOUNDS_MS) + 1))


class RequestTimer:
    def __init__(self) -> None:
        self._buckets: dict[tuple[datetime, str, str], _Bucket] = {}
        self._task: asyncio.Task | None = None

    def record(self, method: str, route: str, status: int, duration_ms: float, *, at: datetime | None = None) -> None:
        minute = (at or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
        bucket = self._buckets.setdefault((minute, method, route), _Bucket())
        bucket.count += 1
        bucket.server_errors += int(status >= 500)
        bucket.client_errors += int(400 <= status < 500)
        bucket.total_ms += duration_ms
        bucket.max_ms = max(bucket.max_ms, duration_ms)
        bucket.histogram[latency_bucket(duration_ms)] += 1

    def take(self, *, finished_before: datetime | None = None) -> list[dict[str, object]]:
        """Remove and return the minutes that have ended (all of them when `finished_before` is None)."""
        cutoff = finished_before.replace(second=0, microsecond=0) if finished_before else None
        keys = [key for key in self._buckets if cutoff is None or key[0] < cutoff]
        release = app_release()
        rows = []
        for key in keys:
            minute, method, route = key
            bucket = self._buckets.pop(key)
            rows.append(
                {
                    "bucket_start": minute,
                    "release": release,
                    "method": method,
                    "route": route,
                    "count": bucket.count,
                    "server_errors": bucket.server_errors,
                    "client_errors": bucket.client_errors,
                    "total_ms": round(bucket.total_ms, 1),
                    "max_ms": round(bucket.max_ms, 1),
                    "histogram_json": bucket.histogram,
                }
            )
        return rows

    def flush(self, *, everything: bool = False) -> None:
        rows = self.take(finished_before=None if everything else datetime.now(timezone.utc))
        try:
            save_request_stats(rows)
        except Exception:
            # Losing a minute of timing is fine; breaking the server over it is not.
            logger.warning("api.request_timing.flush_failed rows=%s", len(rows), exc_info=True)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        await asyncio.to_thread(self.flush, everything=True)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            await asyncio.to_thread(self.flush)


request_timer = RequestTimer()

__all__ = ["RequestTimer", "app_release", "request_timer"]
