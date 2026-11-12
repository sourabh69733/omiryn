"""Fast read models for the admin pages: dashboard, people, costs, system.

Each page runs a few aggregate queries in parallel instead of loading whole tables, so a
page costs one round trip to the database, not twenty. Chat text and memory text are never
read here: admins see counts, health and timing, not what people said.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import and_, case, distinct, func, literal, literal_column, or_, select, union, union_all

from storage import ENGINE
from storage.schema import (
    agent_conversations,
    agent_eval_runs,
    agent_jobs,
    agent_memories,
    agent_message_feedback,
    agent_open_questions,
    agent_self_notes,
    agent_usage_events,
    agent_user_settings,
    agent_vibe_cards,
    app_events,
    audit_events,
    channel_link_codes,
    channel_links,
    conversation_threads,
    data_requests,
    feedback_submissions,
    live_presence,
    match_pairs,
    match_pool_members,
    match_pools,
    memory_batch_failures,
    profile_facts,
    memory_processing_leases,
    upload_digests,
    user_profiles,
    whatsapp_imports,
)

CHAT_REPLY = "chat_reply"
BAD_RATINGS = ("off", "bad", "harmful")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run(queries: dict[str, Callable[[Any], Any]]) -> dict[str, Any]:
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


def _day(column: Any) -> Any:
    if ENGINE.dialect.name == "postgresql":
        return func.date(func.timezone(literal_column("'UTC'"), column))
    return func.date(column)


def _channel() -> Any:
    # A literal, not a bound value, so Postgres sees the same expression in SELECT and GROUP BY.
    return func.coalesce(agent_conversations.c.channel, literal_column("'web'"))


def _day_key(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)[:10]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _float(value: Any) -> float:
    return round(float(value or 0), 6)


def _int(value: Any) -> int:
    return int(value or 0)


def _clip(value: Any, limit: int = 240) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _percentile(values: list[int], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return int(ordered[index])


def _activity():
    """Every signed-in action that counts as someone using Omiryn: app events and Omi's replies."""
    return union_all(
        select(app_events.c.user_id.label("user_id"), app_events.c.created_at.label("at")).where(
            app_events.c.user_id.is_not(None)
        ),
        select(agent_usage_events.c.user_id.label("user_id"), agent_usage_events.c.created_at.label("at")).where(
            agent_usage_events.c.user_id.is_not(None), agent_usage_events.c.request_kind == CHAT_REPLY
        ),
    ).subquery("activity")


def _known_users():
    return union(
        select(user_profiles.c.user_id.label("user_id")),
        select(agent_conversations.c.user_id.label("user_id")).where(agent_conversations.c.user_id.is_not(None)),
    ).subquery("known_users")


def _count(connection: Any, table: Any, *where: Any) -> int:
    statement = select(func.count()).select_from(table)
    if where:
        statement = statement.where(*where)
    return _int(connection.execute(statement).scalar())


# --- Dashboard -----------------------------------------------------------------------------


def admin_dashboard(days: int = 14) -> dict[str, Any]:
    days = max(7, min(days, 90))
    now = _now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = now - timedelta(days=7)
    two_weeks = now - timedelta(days=14)
    month = now - timedelta(days=30)
    window = today - timedelta(days=days - 1)

    def kpis(connection: Any) -> dict[str, Any]:
        activity = _activity()
        first_seen = (
            select(activity.c.user_id, func.min(activity.c.at).label("first_at"))
            .group_by(activity.c.user_id)
            .subquery("first_seen")
        )
        known = _known_users()
        usage = agent_usage_events.c
        reply = usage.request_kind == CHAT_REPLY

        def active_between(start: datetime, end: datetime | None = None) -> Any:
            conditions = [activity.c.at >= start]
            if end is not None:
                conditions.append(activity.c.at < end)
            return select(func.count(distinct(activity.c.user_id))).where(*conditions).scalar_subquery()

        def usage_sum(expression: Any, *conditions: Any) -> Any:
            return select(func.coalesce(func.sum(expression), 0)).where(*conditions).scalar_subquery()

        recent_active = select(distinct(activity.c.user_id)).where(activity.c.at >= week)
        row = connection.execute(
            select(
                select(func.count()).select_from(known).scalar_subquery().label("users_total"),
                select(func.count()).where(user_profiles.c.created_at >= week).scalar_subquery().label("new_users_7d"),
                select(func.count()).where(user_profiles.c.created_at >= today).scalar_subquery().label("new_users_today"),
                active_between(today).label("active_today"),
                active_between(week).label("active_7d"),
                active_between(two_weeks, week).label("active_prev_7d"),
                active_between(month).label("active_30d"),
                select(func.count())
                .select_from(first_seen)
                .where(first_seen.c.first_at < week, first_seen.c.user_id.in_(recent_active))
                .scalar_subquery()
                .label("returning_7d"),
                usage_sum(case((usage.success, 1), else_=0), reply, usage.created_at >= today).label("replies_today"),
                usage_sum(case((usage.success, 1), else_=0), reply, usage.created_at >= week).label("replies_7d"),
                usage_sum(
                    case((usage.success, 1), else_=0), reply, usage.created_at >= two_weeks, usage.created_at < week
                ).label("replies_prev_7d"),
                usage_sum(case((usage.success, 0), else_=1), reply, usage.created_at >= today).label("failed_today"),
                usage_sum(case((usage.success, 0), else_=1), reply, usage.created_at >= week).label("failed_7d"),
                usage_sum(usage.estimated_cost_usd, usage.created_at >= today).label("cost_today"),
                usage_sum(usage.estimated_cost_usd, usage.created_at >= week).label("cost_7d"),
                usage_sum(usage.estimated_cost_usd, usage.created_at >= month).label("cost_30d"),
                select(func.count())
                .where(app_events.c.event_name.like("quota.chat%"), app_events.c.created_at >= week)
                .scalar_subquery()
                .label("messages_7d"),
            )
        ).mappings().one()
        return {key: (_float(value) if key.startswith("cost") else _int(value)) for key, value in row.items()}

    def daily(connection: Any) -> list[dict[str, Any]]:
        activity = _activity()
        usage = agent_usage_events.c
        active_day = _day(activity.c.at)
        usage_day = _day(usage.created_at)
        profile_day = _day(user_profiles.c.created_at)
        rows = connection.execute(
            union_all(
                select(
                    literal("active").label("metric"),
                    active_day.label("day"),
                    func.count(distinct(activity.c.user_id)).label("value"),
                )
                .where(activity.c.at >= window)
                .group_by(active_day),
                select(
                    literal("replies").label("metric"),
                    usage_day.label("day"),
                    func.sum(case((usage.success, 1), else_=0)).label("value"),
                )
                .where(usage.request_kind == CHAT_REPLY, usage.created_at >= window)
                .group_by(usage_day),
                select(
                    literal("failed").label("metric"),
                    usage_day.label("day"),
                    func.sum(case((usage.success, 0), else_=1)).label("value"),
                )
                .where(usage.request_kind == CHAT_REPLY, usage.created_at >= window)
                .group_by(usage_day),
                select(
                    literal("cost").label("metric"),
                    usage_day.label("day"),
                    func.coalesce(func.sum(usage.estimated_cost_usd), 0).label("value"),
                )
                .where(usage.created_at >= window)
                .group_by(usage_day),
                select(literal("new").label("metric"), profile_day.label("day"), func.count().label("value"))
                .where(user_profiles.c.created_at >= window)
                .group_by(profile_day),
            )
        ).all()
        series: dict[str, dict[str, float]] = {}
        for metric, day, value in rows:
            series.setdefault(_day_key(day), {})[metric] = float(value or 0)
        result = []
        for offset in range(days):
            key = (window + timedelta(days=offset)).date().isoformat()
            values = series.get(key, {})
            result.append(
                {
                    "date": key,
                    "active_users": int(values.get("active", 0)),
                    "replies": int(values.get("replies", 0)),
                    "failed_replies": int(values.get("failed", 0)),
                    "cost_usd": round(values.get("cost", 0.0), 6),
                    "new_users": int(values.get("new", 0)),
                }
            )
        return result

    def latency(connection: Any) -> list[int]:
        usage = agent_usage_events.c
        return [
            int(value)
            for (value,) in connection.execute(
                select(usage.latency_ms)
                .where(usage.request_kind == CHAT_REPLY, usage.success, usage.latency_ms.is_not(None), usage.created_at >= week)
                .order_by(usage.created_at.desc())
                .limit(2000)
            ).all()
        ]

    def omi(connection: Any) -> dict[str, Any]:
        usage = agent_usage_events.c
        latest = connection.execute(
            select(usage.provider, usage.model, usage.created_at)
            .where(usage.request_kind == CHAT_REPLY, usage.success)
            .order_by(usage.created_at.desc())
            .limit(1)
        ).first()
        ratings = dict(
            connection.execute(
                select(agent_message_feedback.c.rating, func.count())
                .where(agent_message_feedback.c.created_at >= month)
                .group_by(agent_message_feedback.c.rating)
            ).all()
        )
        last_error = connection.execute(
            select(usage.error, usage.created_at)
            .where(usage.request_kind == CHAT_REPLY, or_(usage.success.is_(False), usage.success.is_(None)))
            .order_by(usage.created_at.desc())
            .limit(1)
        ).first()
        return {
            "prompt_version": _prompt_version(),
            "reply_provider": latest.provider if latest else None,
            "reply_model": latest.model if latest else None,
            "last_reply_at": _iso(latest.created_at) if latest else None,
            "feedback_30d": {
                "good": _int(ratings.get("good")),
                "bad": sum(_int(ratings.get(rating)) for rating in BAD_RATINGS),
                "total": sum(_int(value) for value in ratings.values()),
            },
            "last_error": _clip(last_error.error) if last_error else None,
            "last_error_at": _iso(last_error.created_at) if last_error else None,
        }

    def health(connection: Any) -> dict[str, Any]:
        memories = agent_memories.c
        jobs = agent_jobs.c
        oldest_pending = connection.execute(
            select(func.min(jobs.run_after)).where(jobs.status == "pending", jobs.run_after <= now)
        ).scalar()
        row = connection.execute(
            select(
                select(func.count()).where(memories.status == "active").scalar_subquery().label("memories_active"),
                select(func.count()).where(memories.created_at >= week).scalar_subquery().label("memories_added_7d"),
                select(func.count(distinct(memories.user_id)))
                .where(memories.status == "active")
                .scalar_subquery()
                .label("users_with_memories"),
                select(func.count()).select_from(memory_batch_failures).scalar_subquery().label("batch_failures"),
                select(func.count()).where(jobs.status == "pending").scalar_subquery().label("jobs_pending"),
                select(func.count()).where(jobs.status == "running").scalar_subquery().label("jobs_running"),
                select(func.count()).where(jobs.status == "failed").scalar_subquery().label("jobs_failed"),
                select(func.count())
                .where(data_requests.c.status == "open")
                .scalar_subquery()
                .label("open_data_requests"),
                select(func.count())
                .where(feedback_submissions.c.created_at >= week)
                .scalar_subquery()
                .label("feedback_7d"),
                select(func.count())
                .where(app_events.c.event_name == "client_error", app_events.c.created_at >= week)
                .scalar_subquery()
                .label("client_errors_7d"),
            )
        ).mappings().one()
        result = {key: _int(value) for key, value in row.items()}
        result["oldest_pending_job_minutes"] = _minutes_since(oldest_pending, now)
        return result

    def reach(connection: Any) -> dict[str, Any]:
        links = dict(
            connection.execute(select(channel_links.c.channel, func.count()).group_by(channel_links.c.channel)).all()
        )
        chats = dict(
            connection.execute(
                select(_channel(), func.count())
                .where(agent_conversations.c.updated_at >= week, agent_conversations.c.import_source_id.is_(None))
                .group_by(_channel())
            ).all()
        )
        result: dict[str, Any] = {}
        result["linked_channels"] = {str(key): _int(value) for key, value in links.items()}
        result["chats_by_channel_7d"] = {str(key): _int(value) for key, value in chats.items()}
        return result

    def recent(connection: Any) -> list[dict[str, Any]]:
        activity = _activity()
        last = (
            select(activity.c.user_id, func.max(activity.c.at).label("last_at"))
            .group_by(activity.c.user_id)
            .order_by(func.max(activity.c.at).desc())
            .limit(8)
            .subquery("last")
        )
        rows = connection.execute(
            select(last.c.user_id, last.c.last_at, user_profiles.c.display_name)
            .select_from(last.outerjoin(user_profiles, user_profiles.c.user_id == last.c.user_id))
            .order_by(last.c.last_at.desc())
        ).all()
        return [
            {"user_id": row.user_id, "display_name": row.display_name, "last_active_at": _iso(row.last_at)}
            for row in rows
        ]

    data = _run(
        {"kpis": kpis, "daily": daily, "latency": latency, "omi": omi, "health": health, "reach": reach, "recent": recent}
    )
    latencies = data["latency"]
    data["omi"].update(
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p95_ms=_percentile(latencies, 0.95),
        latency_samples=len(latencies),
    )
    data["health"].update(data["reach"])
    return {
        "generated_at": now.isoformat(),
        "days": days,
        "kpis": data["kpis"],
        "daily": data["daily"],
        "omi": data["omi"],
        "health": data["health"],
        "recent_users": data["recent"],
        "attention": _attention(data["kpis"], data["omi"], data["health"]),
    }


def _attention(kpis: dict[str, Any], omi: dict[str, Any], health: dict[str, Any]) -> list[dict[str, Any]]:
    """Things an operator should look at, worst first. Empty means all clear."""
    items: list[dict[str, Any]] = []

    def add(level: str, title: str, detail: str, route: str, count: int | None = None) -> None:
        items.append({"level": level, "title": title, "detail": detail, "route": route, "count": count})

    if kpis["failed_today"]:
        add("bad", "Failed replies today", omi.get("last_error") or "A reply did not reach the user.", "/usage", kpis["failed_today"])
    if health["jobs_failed"]:
        add("bad", "Background jobs failed", "Jobs that gave up after retries.", "/system", health["jobs_failed"])
    if health["batch_failures"]:
        add("bad", "Memory batches failing", "Chats whose memories could not be saved.", "/system", health["batch_failures"])
    if (health.get("oldest_pending_job_minutes") or 0) >= 30:
        add("warn", "Job queue is behind", f"Oldest job has waited {health['oldest_pending_job_minutes']} min.", "/system", health["jobs_pending"])
    if health["open_data_requests"]:
        add("warn", "Open data requests", "Export or deletion requests waiting.", "/requests", health["open_data_requests"])
    if health["client_errors_7d"]:
        add("warn", "App errors this week", "Errors reported by the web app.", "/requests", health["client_errors_7d"])
    if omi["feedback_30d"]["bad"]:
        add("info", "Replies rated poorly", "Thumbs down in the last 30 days.", "/users", omi["feedback_30d"]["bad"])
    if health["feedback_7d"]:
        add("info", "New feedback", "Messages sent from the feedback form.", "/requests", health["feedback_7d"])
    return items


def _minutes_since(value: Any, now: datetime) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((now - value).total_seconds() // 60))


def _prompt_version() -> str | None:
    try:
        from agent.context_engine.prompt_engine.registry import get_prompt_behavior_version

        return get_prompt_behavior_version().version_id
    except Exception:  # The page still loads if the agent package cannot be imported.
        return None


# --- People --------------------------------------------------------------------------------


def admin_people(limit: int = 500) -> dict[str, Any]:
    limit = max(1, min(limit, 1000))
    now = _now()
    week = now - timedelta(days=7)

    def people(connection: Any) -> list[dict[str, Any]]:
        known = _known_users()
        activity = _activity()
        usage = agent_usage_events.c
        last = (
            select(activity.c.user_id, func.max(activity.c.at).label("last_at"), func.min(activity.c.at).label("first_at"))
            .group_by(activity.c.user_id)
            .subquery("last")
        )
        spend = (
            select(
                usage.user_id,
                func.sum(case((and_(usage.request_kind == CHAT_REPLY, usage.success), 1), else_=0)).label("replies"),
                func.sum(
                    case((and_(usage.request_kind == CHAT_REPLY, usage.success, usage.created_at >= week), 1), else_=0)
                ).label("replies_7d"),
                func.sum(case((and_(usage.request_kind == CHAT_REPLY, usage.success.is_(False)), 1), else_=0)).label(
                    "failed"
                ),
                func.coalesce(func.sum(usage.estimated_cost_usd), 0).label("cost"),
            )
            .where(usage.user_id.is_not(None))
            .group_by(usage.user_id)
            .subquery("spend")
        )
        chats = (
            select(
                agent_conversations.c.user_id,
                func.count().label("chats"),
                func.max(_channel()).label("channel"),
            )
            .where(agent_conversations.c.import_source_id.is_(None))
            .group_by(agent_conversations.c.user_id)
            .subquery("chats")
        )
        memories = (
            select(agent_memories.c.user_id, func.count().label("memories"))
            .where(agent_memories.c.status == "active")
            .group_by(agent_memories.c.user_id)
            .subquery("memories")
        )
        links = (
            select(channel_links.c.user_id, func.count().label("links"))
            .group_by(channel_links.c.user_id)
            .subquery("links")
        )
        facts = (
            select(profile_facts.c.user_id, func.count().label("facts"))
            .group_by(profile_facts.c.user_id)
            .subquery("facts")
        )
        rows = connection.execute(
            select(
                known.c.user_id,
                user_profiles.c.display_name,
                user_profiles.c.city,
                user_profiles.c.country,
                user_profiles.c.created_at.label("joined_at"),
                last.c.last_at,
                last.c.first_at,
                spend.c.replies,
                spend.c.replies_7d,
                spend.c.failed,
                spend.c.cost,
                chats.c.chats,
                memories.c.memories,
                links.c.links,
                facts.c.facts,
            )
            .select_from(
                known.outerjoin(user_profiles, user_profiles.c.user_id == known.c.user_id)
                .outerjoin(last, last.c.user_id == known.c.user_id)
                .outerjoin(spend, spend.c.user_id == known.c.user_id)
                .outerjoin(chats, chats.c.user_id == known.c.user_id)
                .outerjoin(memories, memories.c.user_id == known.c.user_id)
                .outerjoin(links, links.c.user_id == known.c.user_id)
                .outerjoin(facts, facts.c.user_id == known.c.user_id)
            )
            .limit(limit)
        ).all()
        result = [
            {
                "user_id": row.user_id,
                "display_name": row.display_name,
                "place": ", ".join(part for part in (row.city, row.country) if part) or None,
                "joined_at": _iso(row.joined_at or row.first_at),
                "last_active_at": _iso(row.last_at),
                "replies": _int(row.replies),
                "replies_7d": _int(row.replies_7d),
                "failed_replies": _int(row.failed),
                "cost_usd": _float(row.cost),
                "chats": _int(row.chats),
                "memories": _int(row.memories),
                "profile_facts": _int(row.facts),
                "linked_channels": _int(row.links),
            }
            for row in rows
        ]
        result.sort(key=lambda person: person["last_active_at"] or "", reverse=True)
        return result

    data = _run({"people": people})
    return {"generated_at": now.isoformat(), "people": data["people"]}


def admin_person(user_id: str) -> dict[str, Any] | None:
    now = _now()
    window = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
    usage = agent_usage_events.c

    def profile(connection: Any) -> dict[str, Any] | None:
        row = connection.execute(select(user_profiles).where(user_profiles.c.user_id == user_id)).mappings().first()
        settings = (
            connection.execute(select(agent_user_settings).where(agent_user_settings.c.user_id == user_id))
            .mappings()
            .first()
        )
        links = connection.execute(
            select(channel_links.c.channel, channel_links.c.created_at).where(channel_links.c.user_id == user_id)
        ).all()
        return {
            "profile": None
            if row is None
            else {
                "display_name": row["display_name"],
                "age": row["age"],
                "city": row["city"],
                "region": row["region"],
                "country": row["country"],
                "has_photo": bool(row["profile_photo_url"] or row["profile_photo_urls"]),
                "adult_confirmed": row["adult_confirmed_at"] is not None,
                "created_at": _iso(row["created_at"]),
                "updated_at": _iso(row["updated_at"]),
            },
            "settings": None
            if settings is None
            else {
                "proactive_enabled": settings["proactive_enabled"],
                "timezone": settings["timezone"],
                "reply_model": settings["reply_model"],
            },
            "channels": [{"channel": channel, "linked_at": _iso(at)} for channel, at in links],
        }

    def matching(connection: Any) -> dict[str, Any]:
        vibe = connection.execute(
            select(agent_vibe_cards.c.milestone, agent_vibe_cards.c.milestone_reached_at).where(
                agent_vibe_cards.c.user_id == user_id
            )
        ).first()
        pools = connection.execute(
            select(match_pools.c.id, match_pools.c.name, match_pool_members.c.joined_at, match_pool_members.c.left_at)
            .select_from(match_pool_members.join(match_pools, match_pools.c.id == match_pool_members.c.pool_id))
            .where(match_pool_members.c.user_id == user_id)
        ).all()
        pairs = _count(connection, match_pairs, or_(match_pairs.c.user_a == user_id, match_pairs.c.user_b == user_id))
        return {
            "milestone": vibe.milestone if vibe else None,
            "milestone_reached_at": _iso(vibe.milestone_reached_at) if vibe else None,
            "pools": [
                {"id": pool_id, "name": name, "joined_at": _iso(joined), "left_at": _iso(left)}
                for pool_id, name, joined, left in pools
            ],
            "pairs": pairs,
        }

    def chats(connection: Any) -> list[dict[str, Any]]:
        replies = (
            select(
                usage.conversation_id,
                func.sum(case((and_(usage.request_kind == CHAT_REPLY, usage.success), 1), else_=0)).label("replies"),
                func.coalesce(func.sum(usage.estimated_cost_usd), 0).label("cost"),
            )
            .where(usage.user_id == user_id)
            .group_by(usage.conversation_id)
            .subquery("replies")
        )
        conversations = agent_conversations.c
        rows = connection.execute(
            select(
                conversations.id,
                conversations.channel,
                conversations.status,
                conversations.temporary,
                conversations.archived_at,
                conversations.import_source_id,
                conversations.agent_model,
                conversations.created_at,
                conversations.updated_at,
                replies.c.replies,
                replies.c.cost,
            )
            .select_from(agent_conversations.outerjoin(replies, replies.c.conversation_id == conversations.id))
            .where(conversations.user_id == user_id)
            .order_by(conversations.updated_at.desc())
            .limit(50)
        ).all()
        return [
            {
                "id": row.id,
                "channel": row.channel or "web",
                "status": row.status,
                "kind": "upload" if row.import_source_id else "temporary" if row.temporary else "chat",
                "archived": row.archived_at is not None,
                "model": row.agent_model,
                "replies": _int(row.replies),
                "cost_usd": _float(row.cost),
                "created_at": _iso(row.created_at),
                "updated_at": _iso(row.updated_at),
            }
            for row in rows
        ]

    def memory(connection: Any) -> dict[str, Any]:
        memories = agent_memories.c
        by_kind = connection.execute(
            select(memories.kind, memories.status, func.count(), func.max(memories.updated_at))
            .where(memories.user_id == user_id)
            .group_by(memories.kind, memories.status)
        ).all()
        kinds: dict[str, dict[str, int]] = {}
        latest = None
        for kind, status, count, updated in by_kind:
            kinds.setdefault(kind or "other", {})[status or "unknown"] = _int(count)
            if updated is not None and (latest is None or _iso(updated) > _iso(latest)):
                latest = updated
        return {
            "by_kind": [
                {"kind": kind, "active": counts.get("active", 0), "total": sum(counts.values())}
                for kind, counts in sorted(kinds.items(), key=lambda item: -sum(item[1].values()))
            ],
            "active": sum(counts.get("active", 0) for counts in kinds.values()),
            "total": sum(sum(counts.values()) for counts in kinds.values()),
            "last_updated_at": _iso(latest),
            **_person_counts(connection, user_id),
        }

    def spend(connection: Any) -> dict[str, Any]:
        day = _day(usage.created_at)
        totals = connection.execute(
            select(
                func.sum(case((and_(usage.request_kind == CHAT_REPLY, usage.success), 1), else_=0)).label("replies"),
                func.sum(case((and_(usage.request_kind == CHAT_REPLY, usage.success.is_(False)), 1), else_=0)).label(
                    "failed"
                ),
                func.count().label("calls"),
                func.coalesce(func.sum(usage.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(usage.estimated_cost_usd), 0).label("cost"),
                func.min(usage.created_at).label("first_at"),
                func.max(usage.created_at).label("last_at"),
            ).where(usage.user_id == user_id)
        ).mappings().one()
        daily_rows = connection.execute(
            select(
                day,
                func.sum(case((and_(usage.request_kind == CHAT_REPLY, usage.success), 1), else_=0)),
                func.coalesce(func.sum(usage.estimated_cost_usd), 0),
            )
            .where(usage.user_id == user_id, usage.created_at >= window)
            .group_by(day)
        ).all()
        by_day = {_day_key(key): (int(replies or 0), float(cost or 0)) for key, replies, cost in daily_rows}
        feedback = dict(
            connection.execute(
                select(agent_message_feedback.c.rating, func.count())
                .where(agent_message_feedback.c.user_id == user_id)
                .group_by(agent_message_feedback.c.rating)
            ).all()
        )
        return {
            "replies": _int(totals["replies"]),
            "failed_replies": _int(totals["failed"]),
            "calls": _int(totals["calls"]),
            "tokens": _int(totals["tokens"]),
            "cost_usd": _float(totals["cost"]),
            "first_at": _iso(totals["first_at"]),
            "last_at": _iso(totals["last_at"]),
            "daily": [
                {
                    "date": (window + timedelta(days=offset)).date().isoformat(),
                    "replies": by_day.get((window + timedelta(days=offset)).date().isoformat(), (0, 0.0))[0],
                    "cost_usd": round(by_day.get((window + timedelta(days=offset)).date().isoformat(), (0, 0.0))[1], 6),
                }
                for offset in range(30)
            ],
            "feedback": {
                "good": _int(feedback.get("good")),
                "bad": sum(_int(feedback.get(rating)) for rating in BAD_RATINGS),
                "total": sum(_int(value) for value in feedback.values()),
            },
        }

    def audit(connection: Any) -> list[dict[str, Any]]:
        rows = connection.execute(
            select(audit_events.c.actor_id, audit_events.c.actor_role, audit_events.c.action, audit_events.c.created_at)
            .where(audit_events.c.target_user_id == user_id)
            .order_by(audit_events.c.created_at.desc())
            .limit(15)
        ).all()
        return [
            {"actor_id": actor, "actor_role": role, "action": action, "created_at": _iso(at)}
            for actor, role, action, at in rows
        ]

    data = _run(
        {"profile": profile, "matching": matching, "chats": chats, "memory": memory, "spend": spend, "audit": audit}
    )
    if data["profile"]["profile"] is None and not data["chats"] and not data["spend"]["calls"]:
        return None
    return {
        "user_id": user_id,
        **data["profile"],
        "matching": data["matching"],
        "chats": data["chats"],
        "memory": data["memory"],
        "usage": data["spend"],
        "audit": data["audit"],
    }


def _person_counts(connection: Any, user_id: str) -> dict[str, int]:
    def count(table: Any, *where: Any) -> Any:
        return select(func.count()).select_from(table).where(*where).scalar_subquery()

    row = connection.execute(
        select(
            count(conversation_threads, conversation_threads.c.user_id == user_id).label("threads"),
            count(agent_self_notes, agent_self_notes.c.user_id == user_id, agent_self_notes.c.status == "open").label(
                "open_notes"
            ),
            count(
                agent_open_questions, agent_open_questions.c.user_id == user_id, agent_open_questions.c.status == "open"
            ).label("open_questions"),
            count(whatsapp_imports, whatsapp_imports.c.user_id == user_id).label("uploads"),
            count(memory_batch_failures, memory_batch_failures.c.user_id == user_id).label("batch_failures"),
            count(profile_facts, profile_facts.c.user_id == user_id).label("profile_facts"),
        )
    ).mappings().one()
    return {key: _int(value) for key, value in row.items()}


# --- Costs ---------------------------------------------------------------------------------


def admin_costs(days: int = 30) -> dict[str, Any]:
    days = max(1, min(days, 90))
    now = _now()
    window = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    usage = agent_usage_events.c
    failed = or_(usage.success.is_(False), usage.success.is_(None))

    def totals(connection: Any) -> dict[str, Any]:
        row = connection.execute(
            select(
                func.count().label("calls"),
                func.sum(case((failed, 1), else_=0)).label("failed"),
                func.coalesce(func.sum(usage.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(usage.completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(usage.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(usage.estimated_cost_usd), 0).label("cost"),
                func.sum(case((and_(usage.request_kind == CHAT_REPLY, usage.success), 1), else_=0)).label("replies"),
                func.count(distinct(usage.user_id)).label("users"),
            ).where(usage.created_at >= window)
        ).mappings().one()
        return {key: (_float(value) if key == "cost" else _int(value)) for key, value in row.items()}

    def daily(connection: Any) -> list[dict[str, Any]]:
        day = _day(usage.created_at)
        rows = connection.execute(
            select(
                day,
                func.count(),
                func.sum(case((failed, 1), else_=0)),
                func.coalesce(func.sum(usage.total_tokens), 0),
                func.coalesce(func.sum(usage.estimated_cost_usd), 0),
                func.sum(case((and_(usage.request_kind == CHAT_REPLY, usage.success), 1), else_=0)),
            )
            .where(usage.created_at >= window)
            .group_by(day)
        ).all()
        by_day = {_day_key(row[0]): row[1:] for row in rows}
        result = []
        for offset in range(days):
            key = (window + timedelta(days=offset)).date().isoformat()
            calls, failures, tokens, cost, replies = by_day.get(key, (0, 0, 0, 0, 0))
            result.append(
                {
                    "date": key,
                    "calls": _int(calls),
                    "failed": _int(failures),
                    "tokens": _int(tokens),
                    "cost_usd": _float(cost),
                    "replies": _int(replies),
                }
            )
        return result

    def breakdown(connection: Any) -> dict[str, Any]:
        def grouped(*columns: Any) -> list[Any]:
            return connection.execute(
                select(
                    *columns,
                    func.count().label("calls"),
                    func.sum(case((failed, 1), else_=0)).label("failed"),
                    func.coalesce(func.sum(usage.total_tokens), 0).label("tokens"),
                    func.coalesce(func.sum(usage.estimated_cost_usd), 0).label("cost"),
                    func.avg(usage.latency_ms).label("avg_latency"),
                )
                .where(usage.created_at >= window)
                .group_by(*columns)
                .order_by(func.count().desc())
            ).mappings().all()

        def shape(row: Any, *keys: str) -> dict[str, Any]:
            return {
                **{key: row[key] for key in keys},
                "calls": _int(row["calls"]),
                "failed": _int(row["failed"]),
                "tokens": _int(row["tokens"]),
                "cost_usd": _float(row["cost"]),
                "avg_latency_ms": None if row["avg_latency"] is None else int(row["avg_latency"]),
            }

        return {
            "by_kind": [shape(row, "request_kind") for row in grouped(usage.request_kind)],
            "by_model": [shape(row, "provider", "model") for row in grouped(usage.provider, usage.model)],
        }

    def latency(connection: Any) -> dict[str, Any]:
        rows = connection.execute(
            select(usage.latency_ms)
            .where(usage.request_kind == CHAT_REPLY, usage.success, usage.latency_ms.is_not(None), usage.created_at >= window)
            .order_by(usage.created_at.desc())
            .limit(5000)
        ).all()
        values = [int(value) for (value,) in rows]
        return {
            "samples": len(values),
            "p50_ms": _percentile(values, 0.5),
            "p90_ms": _percentile(values, 0.9),
            "p95_ms": _percentile(values, 0.95),
            "max_ms": max(values) if values else None,
        }

    def recent(connection: Any) -> dict[str, Any]:
        columns = (
            usage.id,
            usage.user_id,
            usage.request_kind,
            usage.provider,
            usage.model,
            usage.success,
            usage.total_tokens,
            usage.latency_ms,
            usage.estimated_cost_usd,
            usage.error,
            usage.created_at,
        )

        def shape(row: Any) -> dict[str, Any]:
            return {
                "id": row.id,
                "user_id": row.user_id,
                "request_kind": row.request_kind,
                "provider": row.provider,
                "model": row.model,
                "success": bool(row.success),
                "tokens": _int(row.total_tokens),
                "latency_ms": row.latency_ms,
                "cost_usd": _float(row.estimated_cost_usd),
                "error": _clip(row.error),
                "created_at": _iso(row.created_at),
            }

        calls = connection.execute(select(*columns).order_by(usage.created_at.desc()).limit(60)).all()
        failures = connection.execute(
            select(*columns).where(failed, usage.created_at >= window).order_by(usage.created_at.desc()).limit(25)
        ).all()
        return {"calls": [shape(row) for row in calls], "failures": [shape(row) for row in failures]}

    data = _run({"totals": totals, "daily": daily, "breakdown": breakdown, "latency": latency, "recent": recent})
    return {
        "generated_at": now.isoformat(),
        "days": days,
        "totals": data["totals"],
        "daily": data["daily"],
        **data["breakdown"],
        "reply_latency": data["latency"],
        "recent_calls": data["recent"]["calls"],
        "recent_failures": data["recent"]["failures"],
    }


# --- System --------------------------------------------------------------------------------


def admin_system() -> dict[str, Any]:
    now = _now()
    day_ago = now - timedelta(days=1)
    week = now - timedelta(days=7)

    def jobs(connection: Any) -> dict[str, Any]:
        jobs_c = agent_jobs.c
        counts = connection.execute(
            select(jobs_c.kind, jobs_c.status, func.count(), func.min(jobs_c.run_after)).group_by(jobs_c.kind, jobs_c.status)
        ).all()
        kinds: dict[str, dict[str, Any]] = {}
        for kind, status, count, oldest in counts:
            entry = kinds.setdefault(kind, {"kind": kind, "pending": 0, "running": 0, "done": 0, "failed": 0, "oldest_pending_minutes": None})
            entry[status] = _int(count)
            if status == "pending":
                entry["oldest_pending_minutes"] = _minutes_since(oldest, now)
        failed = connection.execute(
            select(jobs_c.id, jobs_c.kind, jobs_c.user_id, jobs_c.attempts, jobs_c.last_error, jobs_c.updated_at)
            .where(or_(jobs_c.status == "failed", and_(jobs_c.status == "pending", jobs_c.attempts > 0)))
            .order_by(jobs_c.updated_at.desc())
            .limit(20)
        ).all()
        return {
            "by_kind": sorted(kinds.values(), key=lambda item: item["kind"]),
            "problems": [
                {
                    "id": row.id,
                    "kind": row.kind,
                    "user_id": row.user_id,
                    "attempts": _int(row.attempts),
                    "last_error": _clip(row.last_error),
                    "updated_at": _iso(row.updated_at),
                }
                for row in failed
            ],
        }

    def memory(connection: Any) -> dict[str, Any]:
        failures = connection.execute(
            select(
                memory_batch_failures.c.batch_key,
                memory_batch_failures.c.user_id,
                memory_batch_failures.c.attempts,
                memory_batch_failures.c.last_error,
                memory_batch_failures.c.updated_at,
            )
            .order_by(memory_batch_failures.c.updated_at.desc())
            .limit(20)
        ).all()
        memories = agent_memories.c
        row = connection.execute(
            select(
                select(func.count()).where(memories.status == "active").scalar_subquery().label("active"),
                select(func.count()).where(memories.created_at >= day_ago).scalar_subquery().label("added_24h"),
                select(func.count()).where(memories.created_at >= week).scalar_subquery().label("added_7d"),
                select(func.count())
                .where(memory_processing_leases.c.expires_at > now)
                .scalar_subquery()
                .label("leases_held"),
                select(func.count()).select_from(whatsapp_imports).scalar_subquery().label("uploads"),
                select(func.count()).where(whatsapp_imports.c.created_at >= week).scalar_subquery().label("uploads_7d"),
                select(func.count()).select_from(upload_digests).scalar_subquery().label("upload_digests"),
            )
        ).mappings().one()
        return {
            **{key: _int(value) for key, value in row.items()},
            "batch_failures": [
                {
                    "batch_key": row.batch_key,
                    "user_id": row.user_id,
                    "attempts": _int(row.attempts),
                    "last_error": _clip(row.last_error),
                    "updated_at": _iso(row.updated_at),
                }
                for row in failures
            ],
        }

    def channels(connection: Any) -> dict[str, Any]:
        links = connection.execute(
            select(channel_links.c.channel, func.count(), func.max(channel_links.c.created_at)).group_by(channel_links.c.channel)
        ).all()
        chats = connection.execute(
            select(_channel(), func.count())
            .where(agent_conversations.c.updated_at >= week, agent_conversations.c.import_source_id.is_(None))
            .group_by(_channel())
        ).all()
        return {
            "links": [{"channel": channel, "count": _int(count), "last_linked_at": _iso(at)} for channel, count, at in links],
            "pending_link_codes": _count(connection, channel_link_codes, channel_link_codes.c.expires_at > now),
            "chats_7d": [{"channel": channel, "count": _int(count)} for channel, count in chats],
            "online_now": _int(
                connection.execute(
                    select(func.count(distinct(live_presence.c.user_id))).where(
                        live_presence.c.seen_at >= now - timedelta(minutes=5)
                    )
                ).scalar()
            ),
        }

    def evals_and_audit(connection: Any) -> dict[str, Any]:
        runs = connection.execute(
            select(
                agent_eval_runs.c.id,
                agent_eval_runs.c.suite_name,
                agent_eval_runs.c.model,
                agent_eval_runs.c.status,
                agent_eval_runs.c.passed,
                agent_eval_runs.c.failed,
                agent_eval_runs.c.total,
                agent_eval_runs.c.created_at,
            )
            .order_by(agent_eval_runs.c.created_at.desc())
            .limit(10)
        ).all()
        audit = connection.execute(
            select(
                audit_events.c.actor_id,
                audit_events.c.actor_role,
                audit_events.c.action,
                audit_events.c.target_user_id,
                audit_events.c.created_at,
            )
            .order_by(audit_events.c.created_at.desc())
            .limit(30)
        ).all()
        return {
            "eval_runs": [
                {
                    "id": row.id,
                    "suite": row.suite_name,
                    "model": row.model,
                    "status": row.status,
                    "passed": _int(row.passed),
                    "failed": _int(row.failed),
                    "total": _int(row.total),
                    "created_at": _iso(row.created_at),
                }
                for row in runs
            ],
            "audit": [
                {
                    "actor_id": row.actor_id,
                    "actor_role": row.actor_role,
                    "action": row.action,
                    "target_user_id": row.target_user_id,
                    "created_at": _iso(row.created_at),
                }
                for row in audit
            ],
        }

    data = _run({"jobs": jobs, "memory": memory, "channels": channels, "rest": evals_and_audit})
    return {
        "generated_at": now.isoformat(),
        "config": _runtime_config(),
        "jobs": data["jobs"],
        "memory": data["memory"],
        "channels": data["channels"],
        **data["rest"],
    }


def _runtime_config() -> dict[str, Any]:
    import os

    def flag(name: str, default: str) -> bool:
        return os.getenv(name, default).strip().lower() == "true"

    return {
        "prompt_version": _prompt_version(),
        "environment": os.getenv("APP_ENV") or "development",
        "proactive_messaging": flag("PROACTIVE_MESSAGING_ENABLED", "false"),
        "identity_check": os.getenv("AGENT_IDENTITY_CHECK", "true").strip().lower() != "false",
        "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "whatsapp_configured": bool(os.getenv("WHATSAPP_ACCESS_TOKEN") or os.getenv("WHATSAPP_TOKEN")),
    }


__all__ = ["admin_costs", "admin_dashboard", "admin_people", "admin_person", "admin_system"]
