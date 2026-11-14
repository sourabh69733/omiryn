"""Read models for the admin Experience and Growth pages.

Experience: does sign-in work, how fast are pages and API calls, where do people spend time,
what breaks. Growth: how new people get started and whether they come back. Built from app
events (names, numbers and codes only), public sign-in events and per-minute API timing.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy import distinct, func, select

from admin.queries import (
    CHAT_REPLY,
    activity_union,
    as_datetime,
    as_int,
    day_key,
    iso,
    percentile,
    run_parallel,
    utc_day,
    utc_now,
)
from storage import histogram_percentile, merge_histograms
from storage.schema import agent_usage_events, api_request_stats, app_events, match_pairs, public_events, user_profiles

SIGN_IN_PUBLIC_EVENTS = ("sign_in_screen_viewed", "sign_in_started", "sign_in_failed", "sign_in_abandoned")
EXPERIENCE_EVENTS = ("page_left", "page_speed", "rage_click", "client_error")
# A visit shorter than this that ends by going elsewhere counts as a quick exit.
QUICK_EXIT_MS = 5000
# Web Vitals, in the order the page shows them.
SPEED_METRICS = ("LCP", "INP", "CLS", "FCP", "TTFB")
# Caps on rows read into Python for one page view; far above today's volume.
MAX_EVENT_ROWS = 50_000
MAX_TIMING_ROWS = 200_000


def _meta(row: Any) -> dict[str, Any]:
    value = row["metadata_json"]
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _share(part: float, whole: float) -> float:
    return round(part / whole, 4) if whole else 0.0


# --- Experience --------------------------------------------------------------------------


def admin_experience(days: int = 7) -> dict[str, Any]:
    days = max(1, min(days, 30))
    now = utc_now()
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    def sign_in_rows(connection: Any) -> dict[str, list[Any]]:
        public = connection.execute(
            select(public_events.c.event_name, public_events.c.session_id, public_events.c.metadata_json, public_events.c.created_at)
            .where(public_events.c.event_name.in_(SIGN_IN_PUBLIC_EVENTS), public_events.c.created_at >= since)
            .limit(MAX_EVENT_ROWS)
        ).mappings().all()
        succeeded = connection.execute(
            select(app_events.c.metadata_json, app_events.c.created_at)
            .where(app_events.c.event_name == "sign_in_succeeded", app_events.c.created_at >= since)
            .limit(MAX_EVENT_ROWS)
        ).mappings().all()
        return {"public": public, "succeeded": succeeded}

    def page_rows(connection: Any) -> list[Any]:
        return connection.execute(
            select(app_events.c.event_name, app_events.c.user_id, app_events.c.page, app_events.c.metadata_json, app_events.c.created_at)
            .where(app_events.c.event_name.in_(EXPERIENCE_EVENTS), app_events.c.created_at >= since)
            .order_by(app_events.c.created_at.desc())
            .limit(MAX_EVENT_ROWS)
        ).mappings().all()

    def timing_rows(connection: Any) -> list[Any]:
        stats = api_request_stats.c
        return connection.execute(
            select(stats.method, stats.route, stats.count, stats.server_errors, stats.client_errors, stats.total_ms, stats.max_ms, stats.histogram_json)
            .where(stats.bucket_start >= since)
            .limit(MAX_TIMING_ROWS)
        ).mappings().all()

    data = run_parallel({"sign_in": sign_in_rows, "pages": page_rows, "timing": timing_rows})
    events = data["pages"]
    by_name: dict[str, list[Any]] = defaultdict(list)
    for row in events:
        by_name[row["event_name"]].append(row)

    return {
        "generated_at": now.isoformat(),
        "days": days,
        "sign_in": _sign_in_summary(data["sign_in"]["public"], data["sign_in"]["succeeded"], since, days),
        "pages": _time_by_page(by_name["page_left"]),
        "speed": _page_speed(by_name["page_speed"]),
        "api": _api_timing(data["timing"]),
        "errors": _client_errors(by_name["client_error"]),
        "rage_clicks": _rage_clicks(by_name["rage_click"]),
        "releases": _releases(events),
    }


def _sign_in_summary(public: list[Any], succeeded: list[Any], since: Any, days: int) -> dict[str, Any]:
    sessions: dict[str, set[str]] = defaultdict(set)
    failures: Counter[str] = Counter()
    daily: dict[str, Counter[str]] = defaultdict(Counter)
    for index, row in enumerate(public):
        name = row["event_name"]
        # An event without a session id still counts once.
        sessions[name].add(row["session_id"] or f"no-session-{index}")
        daily[day_key(as_datetime(row["created_at"]))][name] += 1
        if name == "sign_in_failed":
            failures[str(_meta(row).get("reason") or "unknown")] += 1
    durations = [value for row in succeeded if (value := _number(_meta(row).get("duration_ms"))) is not None]
    for row in succeeded:
        daily[day_key(as_datetime(row["created_at"]))]["sign_in_succeeded"] += 1

    started = len(sessions["sign_in_started"])
    return {
        "screen_sessions": len(sessions["sign_in_screen_viewed"]),
        "started": started,
        "succeeded": len(succeeded),
        "failed": sum(failures.values()),
        "abandoned": len(sessions["sign_in_abandoned"]),
        "success_rate": _share(len(succeeded), started),
        "duration_p50_ms": percentile(durations, 0.5),
        "duration_p90_ms": percentile(durations, 0.9),
        "failures": [{"reason": reason, "count": count} for reason, count in failures.most_common(10)],
        "daily": [
            {
                "date": key,
                "started": daily[key]["sign_in_started"],
                "succeeded": daily[key]["sign_in_succeeded"],
                "failed": daily[key]["sign_in_failed"],
            }
            for key in ((since + timedelta(days=offset)).date().isoformat() for offset in range(days))
        ],
    }


def _time_by_page(rows: list[Any]) -> list[dict[str, Any]]:
    pages: dict[str, dict[str, Any]] = defaultdict(lambda: {"visits": 0, "active_ms": 0.0, "visible": [], "quick": 0, "users": set()})
    for row in rows:
        meta = _meta(row)
        page = pages[row["page"] or "unknown"]
        visible = _number(meta.get("visible_ms")) or 0.0
        page["visits"] += 1
        page["active_ms"] += _number(meta.get("active_ms")) or 0.0
        page["visible"].append(visible)
        page["quick"] += int(meta.get("reason") == "navigate" and visible < QUICK_EXIT_MS)
        if row["user_id"]:
            page["users"].add(row["user_id"])
    total_active = sum(page["active_ms"] for page in pages.values())
    result = [
        {
            "page": name,
            "visits": page["visits"],
            "users": len(page["users"]),
            "active_ms": round(page["active_ms"]),
            "share": _share(page["active_ms"], total_active),
            "median_visit_ms": percentile(page["visible"], 0.5),
            "quick_exit_rate": _share(page["quick"], page["visits"]),
        }
        for name, page in pages.items()
    ]
    return sorted(result, key=lambda page: -page["active_ms"])


def _page_speed(rows: list[Any]) -> dict[str, Any]:
    values: dict[tuple[str, str], list[float]] = defaultdict(list)
    good: Counter[tuple[str, str]] = Counter()
    for row in rows:
        meta = _meta(row)
        metric, value = meta.get("metric"), _number(meta.get("value"))
        if metric not in SPEED_METRICS or value is None:
            continue
        for key in ((row["page"] or "unknown", metric), ("all", metric)):
            values[key].append(value)
            good[key] += int(meta.get("rating") == "good")

    def summary(page: str) -> dict[str, Any]:
        metrics = {}
        for metric in SPEED_METRICS:
            samples = values.get((page, metric), [])
            if samples:
                p75 = sorted(samples)[min(len(samples) - 1, round(0.75 * (len(samples) - 1)))]
                metrics[metric] = {
                    "p75": round(p75, 3) if metric == "CLS" else round(p75),
                    "samples": len(samples),
                    "good_share": _share(good[(page, metric)], len(samples)),
                }
        return {"page": page, "metrics": metrics}

    pages = sorted({page for page, _ in values if page != "all"})
    return {"overall": summary("all"), "pages": [summary(page) for page in pages]}


def _api_timing(rows: list[Any]) -> dict[str, Any]:
    routes: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "server_errors": 0, "client_errors": 0, "total_ms": 0.0, "max_ms": 0.0, "histograms": []}
    )
    for row in rows:
        route = routes[(row["method"], row["route"])]
        route["calls"] += as_int(row["count"])
        route["server_errors"] += as_int(row["server_errors"])
        route["client_errors"] += as_int(row["client_errors"])
        route["total_ms"] += float(row["total_ms"] or 0)
        route["max_ms"] = max(route["max_ms"], float(row["max_ms"] or 0))
        route["histograms"].append(row["histogram_json"] or [])

    result = []
    for (method, path), route in routes.items():
        histogram = merge_histograms(route["histograms"])
        result.append(
            {
                "method": method,
                "route": path,
                "calls": route["calls"],
                "server_errors": route["server_errors"],
                "client_errors": route["client_errors"],
                "avg_ms": round(route["total_ms"] / route["calls"]) if route["calls"] else None,
                "p50_ms": histogram_percentile(histogram, 0.5),
                "p95_ms": histogram_percentile(histogram, 0.95),
                "max_ms": round(route["max_ms"]),
            }
        )
    all_histogram = merge_histograms(histogram for route in routes.values() for histogram in route["histograms"])
    calls = sum(route["calls"] for route in routes.values())
    return {
        "calls": calls,
        "server_errors": sum(route["server_errors"] for route in routes.values()),
        "p50_ms": histogram_percentile(all_histogram, 0.5),
        "p95_ms": histogram_percentile(all_histogram, 0.95),
        "routes": sorted(result, key=lambda route: (-(route["p95_ms"] or 0), -route["calls"])),
    }


def _client_errors(rows: list[Any]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        meta = _meta(row)
        key = (str(meta.get("message_code") or "unknown"), str(meta.get("source") or ""), row["page"] or "unknown")
        group = groups.setdefault(key, {"count": 0, "users": set(), "releases": set(), "last_at": None, "area": meta.get("area")})
        group["count"] += 1
        if row["user_id"]:
            group["users"].add(row["user_id"])
        if meta.get("release"):
            group["releases"].add(str(meta["release"]))
        created = iso(row["created_at"])
        group["last_at"] = max(filter(None, (group["last_at"], created)), default=None)
    result = [
        {
            "message_code": code,
            "source": source or None,
            "page": page,
            "area": group["area"],
            "count": group["count"],
            "users": len(group["users"]),
            "releases": sorted(group["releases"]),
            "last_at": group["last_at"],
        }
        for (code, source, page), group in groups.items()
    ]
    return sorted(result, key=lambda error: (-error["users"], -error["count"]))[:30]


def _rage_clicks(rows: list[Any]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    users: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        key = (row["page"] or "unknown", str(_meta(row).get("target") or "unknown"))
        counts[key] += 1
        if row["user_id"]:
            users[key].add(row["user_id"])
    return [
        {"page": page, "target": target, "count": count, "users": len(users[(page, target)])}
        for (page, target), count in counts.most_common(20)
    ]


def _releases(rows: Iterable[Any]) -> list[dict[str, Any]]:
    events: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    for row in rows:
        release = str(_meta(row).get("release") or "unknown")
        events[release] += 1
        errors[release] += int(row["event_name"] == "client_error")
        created = iso(row["created_at"]) or ""
        first_seen[release] = min(first_seen.get(release, created), created)
    return sorted(
        ({"release": release, "events": count, "errors": errors[release], "first_seen": first_seen[release]} for release, count in events.items()),
        key=lambda release: release["first_seen"],
        reverse=True,
    )[:10]


# --- Growth ------------------------------------------------------------------------------


def admin_growth(weeks: int = 8) -> dict[str, Any]:
    weeks = max(2, min(weeks, 26))
    now = utc_now()
    today = now.date()
    first_monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    funnel_since = now - timedelta(days=30)

    def active_days(connection: Any) -> dict[str, Any]:
        activity = activity_union()
        first = connection.execute(
            select(activity.c.user_id, func.min(activity.c.at)).group_by(activity.c.user_id)
        ).all()
        day = utc_day(activity.c.at)
        days_rows = connection.execute(
            select(activity.c.user_id, day).where(activity.c.at >= first_monday).group_by(activity.c.user_id, day)
        ).all()
        return {"first": first, "days": days_rows}

    def funnel_rows(connection: Any) -> dict[str, Any]:
        def sessions(name: str) -> int:
            return as_int(
                connection.execute(
                    select(func.count(distinct(public_events.c.session_id))).where(
                        public_events.c.event_name == name, public_events.c.created_at >= funnel_since
                    )
                ).scalar()
            )

        replies = connection.execute(
            select(agent_usage_events.c.user_id, func.min(agent_usage_events.c.created_at))
            .where(agent_usage_events.c.request_kind == CHAT_REPLY, agent_usage_events.c.success, agent_usage_events.c.user_id.is_not(None))
            .group_by(agent_usage_events.c.user_id)
        ).all()
        messages = connection.execute(
            select(distinct(app_events.c.user_id)).where(app_events.c.event_name.like("quota.chat%"))
        ).scalars().all()
        profiles = connection.execute(select(user_profiles.c.user_id)).scalars().all()
        return {
            "screen_sessions": sessions("sign_in_screen_viewed"),
            "started_sessions": sessions("sign_in_started"),
            "first_reply": dict(replies),
            "messaged": set(messages),
            "profiles": set(profiles),
        }

    def pair_statuses(connection: Any) -> dict[str, int]:
        return {status: as_int(count) for status, count in connection.execute(
            select(match_pairs.c.status, func.count()).group_by(match_pairs.c.status)
        ).all()}

    data = run_parallel({"activity": active_days, "funnel": funnel_rows, "pairs": pair_statuses})
    first_seen = {user_id: as_datetime(at) for user_id, at in data["activity"]["first"] if at is not None}
    active: dict[str, set[date]] = defaultdict(set)
    for user_id, day in data["activity"]["days"]:
        active[user_id].add(date.fromisoformat(day_key(day)))

    return {
        "generated_at": now.isoformat(),
        "weeks": weeks,
        "returns": _return_rates(first_seen, active, today),
        "cohorts": _cohorts(first_seen, active, first_monday, weeks, today),
        "getting_started": _getting_started(data["funnel"], first_seen, active, funnel_since, today),
        "matching": _matching_funnel(data["pairs"]),
    }


def _came_back(first_day: date, days: set[date], start: int, end: int) -> bool:
    return any(start <= (day - first_day).days <= end for day in days)


def _return_rates(first_seen: dict[str, Any], active: dict[str, set[date]], today: date) -> list[dict[str, Any]]:
    """Of the people who joined long enough ago, how many were active again in each window."""
    windows = (
        ("next_day", "Came back the next day", 1, 1),
        ("first_week", "Came back within a week", 1, 7),
        ("week_two", "Active in their second week", 7, 13),
        ("month", "Active a month later (days 28-34)", 28, 34),
    )
    result = []
    for key, label, start, end in windows:
        eligible = [user for user, first in first_seen.items() if (today - first.date()).days >= end]
        returned = sum(_came_back(first_seen[user].date(), active.get(user, set()), start, end) for user in eligible)
        result.append({"key": key, "label": label, "eligible": len(eligible), "returned": returned, "rate": _share(returned, len(eligible))})
    return result


def _cohorts(first_seen: dict[str, Any], active: dict[str, set[date]], first_monday: date, weeks: int, today: date) -> list[dict[str, Any]]:
    """Users by the week they joined, and the share active in each week after joining."""
    members: dict[date, list[str]] = defaultdict(list)
    for user, first in first_seen.items():
        joined = first.date()
        week_start = joined - timedelta(days=joined.weekday())
        if week_start >= first_monday:
            members[week_start].append(user)
    result = []
    for index in range(weeks):
        week_start = first_monday + timedelta(weeks=index)
        users = members.get(week_start, [])
        elapsed = (today - week_start).days // 7
        shares = []
        for offset in range(weeks - index):
            if offset > elapsed:
                shares.append(None)
                continue
            returned = sum(
                any((day - first_seen[user].date()).days // 7 == offset for day in active.get(user, set())) for user in users
            )
            shares.append(_share(returned, len(users)) if users else None)
        result.append({"week_start": week_start.isoformat(), "users": len(users), "active_share_by_week": shares})
    return list(reversed(result))


def _getting_started(funnel: dict[str, Any], first_seen: dict[str, Any], active: dict[str, set[date]], since: Any, today: date) -> dict[str, Any]:
    new_users = [user for user, first in first_seen.items() if first >= since]
    first_reply = {user: as_datetime(at) for user, at in funnel["first_reply"].items()}
    minutes_to_reply = [
        (first_reply[user] - first_seen[user]).total_seconds() / 60 for user in new_users if user in first_reply
    ]
    week_eligible = [user for user in new_users if (today - first_seen[user].date()).days >= 13]
    steps = [
        ("Saw the sign-in screen", funnel["screen_sessions"], "sessions"),
        ("Started Google sign-in", funnel["started_sessions"], "sessions"),
        ("Signed in (new users)", len(new_users), "users"),
        ("Finished setup", sum(user in funnel["profiles"] for user in new_users), "users"),
        ("Sent a message", sum(user in funnel["messaged"] or user in first_reply for user in new_users), "users"),
        ("Got a reply from Omi", sum(user in first_reply for user in new_users), "users"),
        ("Came back another day", sum(_came_back(first_seen[u].date(), active.get(u, set()), 1, 10_000) for u in new_users), "users"),
    ]
    return {
        "days": 30,
        "steps": [{"label": label, "count": count, "unit": unit} for label, count, unit in steps],
        "second_week": {
            "eligible": len(week_eligible),
            "returned": sum(_came_back(first_seen[u].date(), active.get(u, set()), 7, 13) for u in week_eligible),
        },
        "minutes_to_first_reply_p50": percentile(minutes_to_reply, 0.5),
    }


def _matching_funnel(statuses: dict[str, int]) -> dict[str, Any]:
    """Pairs that reached each stage. Status is where a pair is now, so a stage counts every later status."""
    reached = {
        "proposed": ("proposed", "asked", "introduced", "met", "no_show", "declined", "still_talking", "expired"),
        "asked": ("asked", "introduced", "met", "no_show", "declined", "still_talking", "expired"),
        "introduced": ("introduced", "met", "no_show", "still_talking"),
        "met": ("met", "still_talking"),
        "still_talking": ("still_talking",),
    }
    labels = {
        "proposed": "Proposed",
        "asked": "Asked both",
        "introduced": "Both said yes, introduced",
        "met": "Met",
        "still_talking": "Still talking",
    }
    return {
        "steps": [{"key": key, "label": labels[key], "count": sum(statuses.get(s, 0) for s in group)} for key, group in reached.items()],
        "declined": statuses.get("declined", 0),
        "expired": statuses.get("expired", 0),
        "no_show": statuses.get("no_show", 0),
    }


__all__ = ["admin_experience", "admin_growth"]
