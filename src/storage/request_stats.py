"""API timing summaries: how many calls each route got per minute, how many failed, and how long they took."""

from __future__ import annotations

from typing import Any, Iterable
from uuid import uuid4

from .database import ENGINE
from .schema import api_request_stats

# Upper bounds of the latency buckets, in milliseconds. A call slower than the last bound counts in one more bucket.
REQUEST_LATENCY_BOUNDS_MS: tuple[int, ...] = (25, 50, 100, 200, 400, 800, 1600, 3200, 6400, 12800, 25600)


def latency_bucket(duration_ms: float) -> int:
    for index, bound in enumerate(REQUEST_LATENCY_BOUNDS_MS):
        if duration_ms <= bound:
            return index
    return len(REQUEST_LATENCY_BOUNDS_MS)


def merge_histograms(histograms: Iterable[list[int]]) -> list[int]:
    merged = [0] * (len(REQUEST_LATENCY_BOUNDS_MS) + 1)
    for histogram in histograms:
        for index, count in enumerate(histogram[: len(merged)]):
            merged[index] += int(count or 0)
    return merged


def histogram_percentile(histogram: list[int], share: float) -> int | None:
    """The bucket bound under which `share` of the calls finished; None for an empty histogram.

    Calls past the last bound report that bound, so read the top value as "more than".
    """
    total = sum(histogram)
    if not total:
        return None
    target = share * total
    seen = 0
    for index, count in enumerate(histogram):
        seen += count
        if seen >= target:
            return REQUEST_LATENCY_BOUNDS_MS[min(index, len(REQUEST_LATENCY_BOUNDS_MS) - 1)]
    return REQUEST_LATENCY_BOUNDS_MS[-1]


def save_request_stats(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with ENGINE.begin() as connection:
        connection.execute(api_request_stats.insert(), [{"id": str(uuid4()), **row} for row in rows])


__all__ = [
    "REQUEST_LATENCY_BOUNDS_MS",
    "histogram_percentile",
    "latency_bucket",
    "merge_histograms",
    "save_request_stats",
]
