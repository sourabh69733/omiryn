"""Measures the numbers the agent was tuned with by hand, from real usage.

Timeouts come from how long model calls actually take; the session gap and the time-note gap
from how people actually pause; bubble limits from how long replies actually run. Pure
functions over plain rows, so the report script only loads data.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

# Pause bands a person would recognise; the session gap and time-note gap sit between them.
GAP_BANDS = (
    ("under 10 min", timedelta(minutes=10)),
    ("10-60 min", timedelta(hours=1)),
    ("1-6 hours", timedelta(hours=6)),
    ("6-24 hours", timedelta(hours=24)),
    ("over a day", None),
)
# A timeout this far above the slowest normal call leaves room for a slow day.
TIMEOUT_HEADROOM = 1.5


def percentile(values: list[float], share: float) -> float | None:
    """Nearest-rank percentile; None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(share * len(ordered)))
    return ordered[rank - 1]


def call_report(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per request kind: calls, failures, latency seconds and output tokens at p50/p90/p99."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("request_kind") or "unknown"), []).append(event)
    report = {}
    for kind, rows in grouped.items():
        ok = [row for row in rows if row.get("success") and row.get("latency_ms")]
        seconds = [row["latency_ms"] / 1000 for row in ok]
        tokens = [float(row.get("completion_tokens") or 0) for row in ok]
        report[kind] = {
            "calls": len(rows),
            "failures": len(rows) - len(ok),
            "p50_s": percentile(seconds, 0.5),
            "p90_s": percentile(seconds, 0.9),
            "p99_s": percentile(seconds, 0.99),
            "max_s": max(seconds) if seconds else None,
            "p50_tokens": percentile(tokens, 0.5),
            "p90_tokens": percentile(tokens, 0.9),
        }
    return report


def suggested_timeout(p99_seconds: float | None, *, low: float, high: float) -> float | None:
    """p99 with headroom, kept within sane bounds, rounded to 5 seconds."""
    if p99_seconds is None:
        return None
    value = min(high, max(low, p99_seconds * TIMEOUT_HEADROOM))
    return float(5 * math.ceil(value / 5))


def pause_report(conversations: Iterable[list[dict[str, Any]]]) -> dict[str, Any]:
    """How long users pause between their own messages, as band shares and percentiles."""
    gaps: list[timedelta] = []
    for messages in conversations:
        times = [t for m in messages if m.get("role") == "user" and (t := _time(m.get("created_at")))]
        gaps.extend(later - earlier for earlier, later in zip(times, times[1:]) if later >= earlier)
    counts = {label: 0 for label, _limit in GAP_BANDS}
    for gap in gaps:
        for label, limit in GAP_BANDS:
            if limit is None or gap < limit:
                counts[label] += 1
                break
    minutes = [gap.total_seconds() / 60 for gap in gaps]
    return {
        "pauses": len(gaps),
        "bands": {label: (count / len(gaps) if gaps else 0.0) for label, count in counts.items()},
        "p50_min": percentile(minutes, 0.5),
        "p90_min": percentile(minutes, 0.9),
    }


def bubble_report(conversations: Iterable[list[dict[str, Any]]]) -> dict[str, Any]:
    """Bubbles per reply, for normal replies and story replies separately."""
    normal: list[float] = []
    story: list[float] = []
    for messages in conversations:
        run: list[dict[str, Any]] = []
        for message in [*messages, {"role": "user"}]:
            if message.get("role") == "assistant" and not message.get("proactive"):
                if run and message.get("created_at") != run[-1].get("created_at"):
                    _add_run(run, normal, story)
                    run = []
                run.append(message)
            elif run:
                _add_run(run, normal, story)
                run = []
    return {
        "normal_replies": len(normal),
        "normal_p90_bubbles": percentile(normal, 0.9),
        "story_replies": len(story),
        "story_p50_bubbles": percentile(story, 0.5),
        "story_p90_bubbles": percentile(story, 0.9),
    }


def _add_run(run: list[dict[str, Any]], normal: list[float], story: list[float]) -> None:
    (story if any(m.get("story") for m in run) else normal).append(float(len(run)))


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


__all__ = [
    "GAP_BANDS",
    "bubble_report",
    "call_report",
    "pause_report",
    "percentile",
    "suggested_timeout",
]
