"""Small query helpers shared by the admin read models: parallel queries, UTC days, value shaping."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy import func, literal_column, select, union_all

from storage import ENGINE
from storage.schema import agent_usage_events, app_events

CHAT_REPLY = "chat_reply"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_parallel(queries: dict[str, Callable[[Any], Any]]) -> dict[str, Any]:
    """Run each query on its own connection at the same time; the page waits for the slowest."""

    def one(fn: Callable[[Any], Any]) -> Any:
        with ENGINE.connect() as connection:
            return fn(connection)

    if ENGINE.dialect.name == "sqlite":
        # One file, one writer: parallel connections buy nothing and can lock.
        return {key: one(fn) for key, fn in queries.items()}
    with ThreadPoolExecutor(max_workers=min(len(queries), 8)) as pool:
        futures = {key: pool.submit(one, fn) for key, fn in queries.items()}
        return {key: future.result() for key, future in futures.items()}


def utc_day(column: Any) -> Any:
    """The UTC calendar day of a timestamp column, as SQL."""
    if ENGINE.dialect.name == "postgresql":
        return func.date(func.timezone(literal_column("'UTC'"), column))
    return func.date(column)


def day_key(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)[:10]


def as_datetime(value: Any) -> datetime | None:
    """A stored timestamp as an aware UTC datetime (SQLite hands back strings or naive values)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return as_datetime(value).astimezone(timezone.utc).isoformat()
    return str(value)


def as_float(value: Any) -> float:
    return round(float(value or 0), 6)


def as_int(value: Any) -> int:
    return int(value or 0)


def clip(value: Any, limit: int = 240) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def percentile(values: list[float], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return int(ordered[index])


def activity_union():
    """Every signed-in action that counts as someone using Omiryn: app events and Omi's replies."""
    return union_all(
        select(app_events.c.user_id.label("user_id"), app_events.c.created_at.label("at")).where(
            app_events.c.user_id.is_not(None)
        ),
        select(agent_usage_events.c.user_id.label("user_id"), agent_usage_events.c.created_at.label("at")).where(
            agent_usage_events.c.user_id.is_not(None), agent_usage_events.c.request_kind == CHAT_REPLY
        ),
    ).subquery("activity")
