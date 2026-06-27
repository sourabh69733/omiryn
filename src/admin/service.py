from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from security.encryption import decrypt_json
from storage import (
    ENGINE,
    _unprotect_messages,
    agent_conversations,
    agent_context_snapshots,
    agent_message_feedback,
    agent_usage_events,
    conversation_context_sources,
    data_point_extraction_debug,
    draft_profiles,
    profile_facts,
    summarize_agent_usage,
    user_profiles,
)


def admin_overview(limit: int = 30) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    snapshot = _load_admin_snapshot()
    usage_events = [_usage_event_from_row(row) for row in snapshot["usage_rows"]]
    usage_summary = summarize_agent_usage()
    users = _admin_users(snapshot, usage_events)
    health = _dashboard_health(users, snapshot["draft_rows"], usage_events)
    activity = _dashboard_activity(
        users,
        snapshot["conversation_rows"],
        snapshot["draft_rows"],
        usage_events,
        snapshot["feedback_rows"],
        snapshot["context_snapshot_rows"],
        snapshot["data_point_review_rows"],
    )

    return {
        "summary": {
            "user_count": len(users),
            **health,
            "anonymous_conversation_count": sum(
                1 for row in snapshot["conversation_rows"] if row["user_id"] is None
            ),
            "conversation_count": len(snapshot["conversation_rows"]),
            "active_conversation_count": sum(
                1 for row in snapshot["conversation_rows"] if row["status"] == "active"
            ),
            "extracted_conversation_count": sum(
                1 for row in snapshot["conversation_rows"] if row["status"] == "extracted"
            ),
            "draft_count": len(snapshot["draft_rows"]),
            "approved_draft_count": sum(
                1 for row in snapshot["draft_rows"] if row["status"] == "approved"
            ),
            "learned_fact_count": len(snapshot["fact_rows"]),
            "context_source_count": len(snapshot["context_rows"]),
            "context_snapshot_count": len(snapshot["context_snapshot_rows"]),
            "data_point_review_count": len(snapshot["data_point_review_rows"]),
            "feedback_count": len(snapshot["feedback_rows"]),
            "usage": usage_summary,
        },
        "activity": activity,
        "limits": configured_usage_limits(),
        "users": users[:limit],
        "recent_conversations": [
            _conversation_summary(row, snapshot["context_rows"], usage_events)
            | _conversation_context_snapshot_summary(row, snapshot["context_snapshot_rows"])
            for row in snapshot["conversation_rows"][:limit]
        ],
        "recent_drafts": [_draft_summary(row) for row in snapshot["draft_rows"][:limit]],
        "recent_usage_events": usage_events[:limit],
    }


def _dashboard_activity(
    users: list[dict[str, Any]],
    conversation_rows: list[Any],
    draft_rows: list[Any],
    usage_events: list[dict[str, Any]],
    feedback_rows: list[Any],
    context_snapshot_rows: list[Any],
    data_point_review_rows: list[Any],
    days: int = 14,
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=days - 1)
    buckets = {
        start_date + timedelta(days=index): {
            "date": (start_date + timedelta(days=index)).isoformat(),
            "label": (start_date + timedelta(days=index)).strftime("%d %b"),
            "new_users": 0,
            "active_users": 0,
            "conversations": 0,
            "api_calls": 0,
            "_active_user_ids": set(),
        }
        for index in range(days)
    }
    active_user_ids_in_window = set()

    for user in users:
        first_seen = _parse_iso_datetime(user.get("first_seen_at"), datetime.min.replace(tzinfo=timezone.utc)).date()
        if first_seen in buckets:
            buckets[first_seen]["new_users"] += 1

    for row in conversation_rows:
        created_at = _date_from_value(row["created_at"])
        if created_at in buckets:
            buckets[created_at]["conversations"] += 1
        updated_at = _date_from_value(row["updated_at"])
        user_id = row["user_id"]
        if updated_at in buckets and user_id:
            buckets[updated_at]["_active_user_ids"].add(user_id)
            active_user_ids_in_window.add(user_id)

    for row in draft_rows:
        updated_at = _date_from_value(row["updated_at"])
        user_id = row["user_id"]
        if updated_at in buckets and user_id:
            buckets[updated_at]["_active_user_ids"].add(user_id)
            active_user_ids_in_window.add(user_id)

    for row in feedback_rows:
        created_at = _date_from_value(row["created_at"])
        user_id = row["user_id"]
        if created_at in buckets and user_id:
            buckets[created_at]["_active_user_ids"].add(user_id)
            active_user_ids_in_window.add(user_id)

    for row in context_snapshot_rows:
        created_at = _date_from_value(row["created_at"])
        user_id = row["user_id"]
        if created_at in buckets and user_id:
            buckets[created_at]["_active_user_ids"].add(user_id)
            active_user_ids_in_window.add(user_id)

    for row in data_point_review_rows:
        created_at = _date_from_value(row["created_at"])
        user_id = row["user_id"]
        if created_at in buckets and user_id:
            buckets[created_at]["_active_user_ids"].add(user_id)
            active_user_ids_in_window.add(user_id)

    for event in usage_events:
        created_at = _date_from_value(event.get("created_at"))
        if created_at in buckets:
            buckets[created_at]["api_calls"] += 1
            if event.get("user_id"):
                buckets[created_at]["_active_user_ids"].add(event["user_id"])
                active_user_ids_in_window.add(event["user_id"])

    daily = []
    for bucket in buckets.values():
        active_user_ids = bucket.pop("_active_user_ids")
        bucket["active_users"] = len(active_user_ids)
        daily.append(bucket)

    return {
        "daily": daily,
        "totals": {
            "new_users": sum(day["new_users"] for day in daily),
            "active_users": len(active_user_ids_in_window),
            "conversations": sum(day["conversations"] for day in daily),
            "api_calls": sum(day["api_calls"] for day in daily),
        },
    }


def admin_user_detail(user_id: str, limit: int = 100) -> dict[str, Any] | None:
    limit = max(1, min(limit, 200))
    snapshot = _load_admin_snapshot()
    usage_events = [_usage_event_from_row(row) for row in snapshot["usage_rows"]]
    users = _admin_users(snapshot, usage_events)
    user = next((candidate for candidate in users if candidate["user_id"] == user_id), None)
    if not user:
        return None

    conversations = [
        _conversation_summary(row, snapshot["context_rows"], usage_events)
        | _conversation_context_snapshot_summary(row, snapshot["context_snapshot_rows"])
        for row in snapshot["conversation_rows"]
        if row["user_id"] == user_id
    ]
    drafts = [
        _draft_summary(row)
        for row in snapshot["draft_rows"]
        if row["user_id"] == user_id
    ]
    facts = [
        _fact_summary(row)
        for row in snapshot["fact_rows"]
        if row["user_id"] == user_id
    ]
    events = [
        event for event in usage_events if event.get("user_id") == user_id
    ]
    feedback = [
        _feedback_detail(row, snapshot["conversation_rows"])
        for row in snapshot["feedback_rows"]
        if row["user_id"] == user_id
    ]
    context_snapshots = [
        _context_snapshot_detail(row)
        for row in snapshot["context_snapshot_rows"]
        if row["user_id"] == user_id
    ]
    data_point_reviews = [
        _data_point_review_detail(row)
        for row in snapshot["data_point_review_rows"]
        if row["user_id"] == user_id
    ]

    return {
        "user": user,
        "profile": user["profile"],
        "facts": facts[:limit],
        "conversations": conversations[:limit],
        "drafts": drafts[:limit],
        "usage_events": events[:limit],
        "feedback": feedback[:limit],
        "feedback_summary": _summarize_feedback(feedback),
        "context_snapshots": context_snapshots[:limit],
        "context_snapshot_summary": _summarize_context_snapshots(context_snapshots),
        "data_point_reviews": data_point_reviews[:limit],
        "data_point_review_summary": _summarize_data_point_reviews(data_point_reviews),
    }


def _load_admin_snapshot() -> dict[str, list[Any]]:
    with ENGINE.begin() as connection:
        return {
            "profile_rows": connection.execute(select(user_profiles)).mappings().all(),
            "conversation_rows": connection.execute(
                select(agent_conversations).order_by(agent_conversations.c.updated_at.desc())
            ).mappings().all(),
            "draft_rows": connection.execute(
                select(draft_profiles).order_by(draft_profiles.c.updated_at.desc())
            ).mappings().all(),
            "fact_rows": connection.execute(select(profile_facts)).mappings().all(),
            "context_rows": connection.execute(select(conversation_context_sources)).mappings().all(),
            "feedback_rows": connection.execute(
                select(agent_message_feedback).order_by(agent_message_feedback.c.created_at.desc())
            ).mappings().all(),
            "context_snapshot_rows": connection.execute(
                select(agent_context_snapshots).order_by(agent_context_snapshots.c.created_at.desc())
            ).mappings().all(),
            "data_point_review_rows": connection.execute(
                select(data_point_extraction_debug).order_by(
                    data_point_extraction_debug.c.created_at.desc()
                )
            ).mappings().all(),
            "usage_rows": connection.execute(
                select(agent_usage_events).order_by(agent_usage_events.c.created_at.desc())
            ).mappings().all(),
        }


def _dashboard_health(
    users: list[dict[str, Any]],
    draft_rows: list[Any],
    usage_events: list[dict[str, Any]],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    today = now.date()
    active_cutoff = now - timedelta(days=7)
    inactive_cutoff = now - timedelta(days=14)

    onboarding_started = [user for user in users if user["conversation_count"] > 0]
    onboarding_completed = [
        user
        for user in users
        if user["extracted_conversation_count"] > 0 or user["draft_count"] > 0
    ]
    approved_profile_users = [user for user in users if user["approved_draft_count"] > 0]
    missing_basics_users = [
        user
        for user in users
        if not user.get("display_name") or not user.get("gender") or not user.get("interested_in")
    ]
    active_users = [
        user
        for user in users
        if _parse_iso_datetime(user.get("last_activity_at"), datetime.min.replace(tzinfo=timezone.utc))
        >= active_cutoff
    ]
    inactive_users = [
        user
        for user in users
        if user["conversation_count"] > 0
        and _parse_iso_datetime(
            user.get("last_activity_at"), datetime.min.replace(tzinfo=timezone.utc)
        )
        < inactive_cutoff
    ]
    new_today = [
        user
        for user in users
        if _parse_iso_datetime(user.get("first_seen_at"), datetime.min.replace(tzinfo=timezone.utc)).date()
        == today
    ]
    new_7d = [
        user
        for user in users
        if _parse_iso_datetime(user.get("first_seen_at"), datetime.min.replace(tzinfo=timezone.utc))
        >= active_cutoff
    ]
    open_drafts = [row for row in draft_rows if row["status"] == "draft"]
    agent_failures_today = [
        event
        for event in usage_events
        if not event["success"]
        and _parse_iso_datetime(
            event.get("created_at"), datetime.min.replace(tzinfo=timezone.utc)
        ).date()
        == today
    ]

    return {
        "active_user_7d_count": len(active_users),
        "onboarding_started_user_count": len(onboarding_started),
        "onboarding_completed_user_count": len(onboarding_completed),
        "approved_profile_user_count": len(approved_profile_users),
        "missing_profile_basics_user_count": len(missing_basics_users),
        "new_user_today_count": len(new_today),
        "new_user_7d_count": len(new_7d),
        "inactive_user_count": len(inactive_users),
        "open_draft_count": len(open_drafts),
        "agent_failure_today_count": len(agent_failures_today),
    }


def configured_usage_limits() -> dict[str, int | None]:
    return {
        "groq_rpd": _int_env("GROQ_RPD_LIMIT"),
        "groq_tpd": _int_env("GROQ_TPD_LIMIT"),
        "groq_rpm": _int_env("GROQ_RPM_LIMIT"),
        "groq_tpm": _int_env("GROQ_TPM_LIMIT"),
        "groq_input_tpd": _int_env("GROQ_INPUT_TPD_LIMIT"),
        "groq_output_tpd": _int_env("GROQ_OUTPUT_TPD_LIMIT"),
    }


def _int_env(name: str) -> int | None:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return None
    try:
        value = int(raw_value)
    except ValueError:
        return None
    return value if value > 0 else None


def _admin_users(snapshot: dict[str, list[Any]], usage_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    user_ids = {
        row["user_id"]
        for key in (
            "profile_rows",
            "conversation_rows",
            "draft_rows",
            "fact_rows",
            "context_rows",
            "feedback_rows",
            "context_snapshot_rows",
            "data_point_review_rows",
        )
        for row in snapshot[key]
        if row["user_id"]
    }
    user_ids.update(event["user_id"] for event in usage_events if event.get("user_id"))

    users = [
        _user_summary(
            user_id,
            snapshot["profile_rows"],
            snapshot["conversation_rows"],
            snapshot["draft_rows"],
            snapshot["fact_rows"],
            snapshot["context_rows"],
            snapshot["feedback_rows"],
            snapshot["context_snapshot_rows"],
            snapshot["data_point_review_rows"],
            usage_events,
        )
        for user_id in user_ids
    ]
    return sorted(users, key=lambda user: user["last_activity_at"] or "", reverse=True)


def _user_summary(
    user_id: str,
    profile_rows: list[Any],
    conversation_rows: list[Any],
    draft_rows: list[Any],
    fact_rows: list[Any],
    context_rows: list[Any],
    feedback_rows: list[Any],
    context_snapshot_rows: list[Any],
    data_point_review_rows: list[Any],
    usage_events: list[dict[str, Any]],
) -> dict[str, Any]:
    profile = next((row for row in profile_rows if row["user_id"] == user_id), None)
    conversations = [row for row in conversation_rows if row["user_id"] == user_id]
    drafts = [row for row in draft_rows if row["user_id"] == user_id]
    facts = [row for row in fact_rows if row["user_id"] == user_id]
    sources = [row for row in context_rows if row["user_id"] == user_id]
    feedback = [row for row in feedback_rows if row["user_id"] == user_id]
    context_snapshots = [row for row in context_snapshot_rows if row["user_id"] == user_id]
    data_point_reviews = [row for row in data_point_review_rows if row["user_id"] == user_id]
    events = [event for event in usage_events if event.get("user_id") == user_id]
    feedback_summary = _summarize_feedback(feedback)
    profile_summary = _profile_summary(profile, drafts)
    activity_dates = [
        *[row["updated_at"] for row in conversations],
        *[row["updated_at"] for row in drafts],
        *[row["updated_at"] for row in facts],
        *[row["created_at"] for row in sources],
        *[row["created_at"] for row in feedback],
        *[row["created_at"] for row in context_snapshots],
        *[row["created_at"] for row in data_point_reviews],
        *[event.get("created_at") for event in events],
    ]
    first_seen_dates = [
        profile["created_at"] if profile else None,
        *[row["created_at"] for row in conversations],
        *[row["created_at"] for row in drafts],
        *[row["created_at"] for row in sources],
        *[row["created_at"] for row in feedback],
        *[row["created_at"] for row in context_snapshots],
        *[row["created_at"] for row in data_point_reviews],
        *[event.get("created_at") for event in events],
    ]

    return {
        "user_id": user_id,
        "display_name": profile_summary["display_name"],
        "display_name_source": profile_summary["source"],
        "gender": profile_summary["gender"],
        "interested_in": profile_summary["interested_in"],
        "profile": profile_summary,
        "conversation_count": len(conversations),
        "active_conversation_count": sum(1 for row in conversations if row["status"] == "active"),
        "extracted_conversation_count": sum(
            1 for row in conversations if row["status"] == "extracted"
        ),
        "message_count": sum(len(_conversation_messages(row)) for row in conversations),
        "user_message_count": sum(
            1
            for row in conversations
            for message in _conversation_messages(row)
            if message.get("role") == "user"
        ),
        "context_source_count": len(sources),
        "draft_count": len(drafts),
        "approved_draft_count": sum(1 for row in drafts if row["status"] == "approved"),
        "learned_fact_count": len(facts),
        "feedback_count": len(feedback),
        "context_snapshot_count": len(context_snapshots),
        "data_point_review_count": len(data_point_reviews),
        "negative_feedback_count": (
            feedback_summary["off"] + feedback_summary["bad"] + feedback_summary["harmful"]
        ),
        "feedback_summary": feedback_summary,
        "usage": _summarize_usage_events(events),
        "first_seen_at": _earliest_isoformat(first_seen_dates),
        "last_activity_at": _latest_isoformat(activity_dates),
    }


def _profile_summary(profile: Any | None, drafts: list[Any] | None = None) -> dict[str, Any]:
    summary = {
        "display_name": profile["display_name"] if profile else None,
        "gender": profile["gender"] if profile else None,
        "interested_in": profile["interested_in"] if profile else None,
        "source": "profile" if profile else "unknown",
        "created_at": _isoformat_utc(profile["created_at"]) if profile else None,
        "updated_at": _isoformat_utc(profile["updated_at"]) if profile else None,
    }
    if summary["display_name"] and summary["gender"] and summary["interested_in"]:
        return summary

    for draft in drafts or []:
        submission = draft["submission_json"] or {}
        has_draft_value = False
        for key in ("display_name", "gender", "interested_in"):
            value = _submission_value(submission.get(key))
            if not summary[key] and value:
                summary[key] = value
                has_draft_value = True
        if has_draft_value:
            summary["source"] = "profile + draft" if profile else "draft"
            summary["updated_at"] = summary["updated_at"] or _isoformat_utc(draft["updated_at"])
            summary["created_at"] = summary["created_at"] or _isoformat_utc(draft["created_at"])
        if summary["display_name"] and summary["gender"] and summary["interested_in"]:
            break

    return summary


def _submission_value(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("value")
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or normalized.lower() == "unknown":
        return None
    return normalized


def _conversation_summary(
    row: Any,
    context_rows: list[Any],
    usage_events: list[dict[str, Any]],
) -> dict[str, Any]:
    messages = _conversation_messages(row)
    conversation_id = row["id"]
    events = [event for event in usage_events if event.get("conversation_id") == conversation_id]
    return {
        "id": conversation_id,
        "user_id": row["user_id"],
        "status": row["status"],
        "agent_provider": row["agent_provider"],
        "agent_model": row["agent_model"],
        "agent_mode": row["agent_mode"] or "know_me",
        "message_count": len(messages),
        "user_message_count": sum(1 for message in messages if message.get("role") == "user"),
        "context_source_count": sum(
            1 for source in context_rows if source["conversation_id"] == conversation_id
        ),
        "usage": _summarize_usage_events(events),
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def _conversation_context_snapshot_summary(
    row: Any,
    context_snapshot_rows: list[Any],
) -> dict[str, Any]:
    conversation_id = row["id"]
    snapshots = [
        snapshot for snapshot in context_snapshot_rows if snapshot["conversation_id"] == conversation_id
    ]
    latest = snapshots[0] if snapshots else None
    return {
        "context_snapshot_count": len(snapshots),
        "latest_context_snapshot": _context_snapshot_detail(latest) if latest else None,
    }


def _context_snapshot_detail(row: Any | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "message_index": row["message_index"],
        "summary": decrypt_json(row["user_id"], row["summary_json"]),
        "context": decrypt_json(row["user_id"], row["context_json"]),
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _summarize_context_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    total_context_chars = sum(
        int((snapshot.get("summary") or {}).get("context_chars") or 0)
        for snapshot in snapshots
    )
    total_context_tokens = sum(
        int((snapshot.get("summary") or {}).get("rough_context_tokens") or 0)
        for snapshot in snapshots
    )
    return {
        "total": len(snapshots),
        "total_context_chars": total_context_chars,
        "total_context_tokens": total_context_tokens,
        "style_guide_count": sum(
            1 for snapshot in snapshots if (snapshot.get("summary") or {}).get("used_style_guide")
        ),
        "data_point_count": sum(
            1 for snapshot in snapshots if (snapshot.get("summary") or {}).get("used_data_points")
        ),
        "structured_whatsapp_count": sum(
            1
            for snapshot in snapshots
            if (snapshot.get("summary") or {}).get("used_structured_whatsapp")
        ),
    }


def _data_point_review_detail(row: Any) -> dict[str, Any]:
    user_id = row["user_id"]
    return {
        "id": row["id"],
        "user_id": user_id,
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "import_id": row["import_id"],
        "candidate_key": row["candidate_key"],
        "decision": row["decision"],
        "candidate": decrypt_json(user_id, row["candidate_json"]),
        "review": decrypt_json(user_id, row["review_json"]),
        "metadata": decrypt_json(user_id, row["metadata_json"]),
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _summarize_data_point_reviews(reviews: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": len(reviews),
        "approve": 0,
        "rewrite": 0,
        "merge": 0,
        "reject": 0,
        "unknown": 0,
    }
    for review in reviews:
        decision = str(review.get("decision") or "unknown")
        if decision not in summary:
            decision = "unknown"
        summary[decision] += 1
    return summary


def _fact_summary(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "category": row["category"],
        "key": row["key"],
        "label": row["label"],
        "confidence": row["confidence"],
        "status": row["status"],
        "used_for_matching": row["used_for_matching"],
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def _draft_summary(row: Any) -> dict[str, Any]:
    submission = row["submission_json"] or {}
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "display_name": submission.get("display_name"),
        "agent_provider": submission.get("agent_provider"),
        "warning_count": len(submission.get("extraction_warnings") or []),
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def _feedback_detail(row: Any, conversation_rows: list[Any]) -> dict[str, Any]:
    conversation = next(
        (candidate for candidate in conversation_rows if candidate["id"] == row["conversation_id"]),
        None,
    )
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "message_index": row["message_index"],
        "rating": row["rating"],
        "reason": row["reason"],
        "comment": row["comment"],
        "message_preview": _feedback_message_preview(conversation, row["message_index"]),
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _feedback_message_preview(conversation: Any | None, message_index: int) -> str | None:
    if not conversation:
        return None
    messages = _conversation_messages(conversation)
    if message_index < 0 or message_index >= len(messages):
        return None
    message = messages[message_index]
    content = str(message.get("content") or "").strip()
    if not content:
        return None
    return content[:180] + ("..." if len(content) > 180 else "")


def _conversation_messages(row: Any) -> list[dict[str, Any]]:
    return _unprotect_messages(row["user_id"], row["messages_json"] or [])


def _summarize_feedback(feedback: list[Any]) -> dict[str, int]:
    ratings = {"good": 0, "off": 0, "bad": 0, "harmful": 0}
    for item in feedback:
        rating = item.get("rating") if isinstance(item, dict) else item["rating"]
        if rating in ratings:
            ratings[rating] += 1
    return {"total": len(feedback), **ratings}


def _usage_event_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "request_kind": row["request_kind"],
        "provider": row["provider"],
        "model": row["model"],
        "success": row["success"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "total_tokens": row["total_tokens"],
        "latency_ms": row["latency_ms"],
        "estimated_cost_usd": row["estimated_cost_usd"],
        "error": row["error"],
        "raw_usage": row["raw_usage_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _summarize_usage_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    successful_events = [event for event in events if event["success"]]
    estimated_cost_usd = round(sum(event["estimated_cost_usd"] or 0 for event in events), 8)
    return {
        "request_count": len(events),
        "successful_request_count": len(successful_events),
        "failed_request_count": len(events) - len(successful_events),
        "prompt_tokens": sum(event["prompt_tokens"] or 0 for event in events),
        "completion_tokens": sum(event["completion_tokens"] or 0 for event in events),
        "total_tokens": sum(event["total_tokens"] or 0 for event in events),
        "estimated_cost_usd": estimated_cost_usd,
    }


def _latest_isoformat(values: list[Any]) -> str | None:
    normalized = [
        _isoformat_utc(value) if not isinstance(value, str) else value
        for value in values
        if value
    ]
    return max(normalized) if normalized else None


def _earliest_isoformat(values: list[Any]) -> str | None:
    normalized = [
        _isoformat_utc(value) if not isinstance(value, str) else value
        for value in values
        if value
    ]
    return min(normalized) if normalized else None


def _parse_iso_datetime(value: Any, default: datetime) -> datetime:
    if not value:
        return default
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return default
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _date_from_value(value: Any) -> Any:
    return _parse_iso_datetime(value, datetime.min.replace(tzinfo=timezone.utc)).date()


def _isoformat_utc(value: Any) -> str | None:
    if not value:
        return None
    if value.tzinfo is None:
        return f"{value.isoformat()}Z"
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
