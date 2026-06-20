from __future__ import annotations

import os
from datetime import timezone
from typing import Any

from sqlalchemy import select

from storage import (
    ENGINE,
    agent_conversations,
    agent_usage_events,
    conversation_context_sources,
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

    return {
        "summary": {
            "user_count": len(users),
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
            "usage": usage_summary,
        },
        "limits": configured_usage_limits(),
        "users": users[:limit],
        "recent_conversations": [
            _conversation_summary(row, snapshot["context_rows"], usage_events)
            for row in snapshot["conversation_rows"][:limit]
        ],
        "recent_drafts": [_draft_summary(row) for row in snapshot["draft_rows"][:limit]],
        "recent_usage_events": usage_events[:limit],
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
            "usage_rows": connection.execute(
                select(agent_usage_events).order_by(agent_usage_events.c.created_at.desc())
            ).mappings().all(),
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
        for key in ("profile_rows", "conversation_rows", "draft_rows", "fact_rows", "context_rows")
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
    usage_events: list[dict[str, Any]],
) -> dict[str, Any]:
    profile = next((row for row in profile_rows if row["user_id"] == user_id), None)
    conversations = [row for row in conversation_rows if row["user_id"] == user_id]
    drafts = [row for row in draft_rows if row["user_id"] == user_id]
    facts = [row for row in fact_rows if row["user_id"] == user_id]
    sources = [row for row in context_rows if row["user_id"] == user_id]
    events = [event for event in usage_events if event.get("user_id") == user_id]
    activity_dates = [
        *[row["updated_at"] for row in conversations],
        *[row["updated_at"] for row in drafts],
        *[row["updated_at"] for row in facts],
        *[row["created_at"] for row in sources],
        *[event.get("created_at") for event in events],
    ]

    return {
        "user_id": user_id,
        "display_name": profile["display_name"] if profile else None,
        "gender": profile["gender"] if profile else None,
        "interested_in": profile["interested_in"] if profile else None,
        "conversation_count": len(conversations),
        "active_conversation_count": sum(1 for row in conversations if row["status"] == "active"),
        "message_count": sum(len(row["messages_json"] or []) for row in conversations),
        "user_message_count": sum(
            1
            for row in conversations
            for message in (row["messages_json"] or [])
            if message.get("role") == "user"
        ),
        "context_source_count": len(sources),
        "draft_count": len(drafts),
        "approved_draft_count": sum(1 for row in drafts if row["status"] == "approved"),
        "learned_fact_count": len(facts),
        "usage": _summarize_usage_events(events),
        "last_activity_at": _latest_isoformat(activity_dates),
    }


def _conversation_summary(
    row: Any,
    context_rows: list[Any],
    usage_events: list[dict[str, Any]],
) -> dict[str, Any]:
    messages = row["messages_json"] or []
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


def _isoformat_utc(value: Any) -> str | None:
    if not value:
        return None
    if value.tzinfo is None:
        return f"{value.isoformat()}Z"
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
