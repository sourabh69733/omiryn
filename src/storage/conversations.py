from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from .database import ENGINE
from .schema import (
    agent_context_snapshots,
    agent_conversations,
    agent_message_feedback,
    agent_trace_steps,
    agent_traces,
    agent_usage_events,
    draft_profiles,
)
from .utils import _isoformat_utc, _owned_update_values, _protect_messages, _unprotect_messages

def save_draft(draft: dict[str, Any], user_id: str | None = None) -> None:
    payload = {
        "id": draft["id"],
        "user_id": user_id,
        "status": draft["status"],
        "submission_json": draft["submission"],
    }
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(draft_profiles.c.id).where(draft_profiles.c.id == draft["id"])
        ).first()
        if existing:
            connection.execute(
                draft_profiles.update()
                .where(draft_profiles.c.id == draft["id"])
                .values(**_owned_update_values(payload, "user_id"), updated_at=func.now())
            )
        else:
            connection.execute(draft_profiles.insert().values(**payload))


def get_draft(draft_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    statement = select(draft_profiles).where(draft_profiles.c.id == draft_id)
    if user_id is not None:
        statement = statement.where(draft_profiles.c.user_id == user_id)

    with ENGINE.begin() as connection:
        row = connection.execute(statement).mappings().first()
    if not row:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "submission": row["submission_json"],
    }


def save_conversation(conversation: dict[str, Any], user_id: str | None = None) -> None:
    conversation_user_id = user_id or conversation.get("user_id")
    payload = {
        "id": conversation["id"],
        "user_id": conversation_user_id,
        "status": conversation["status"],
        "agent_provider": conversation.get("agent_provider"),
        "agent_model": conversation.get("agent_model"),
        "agent_mode": conversation.get("agent_mode") or "know_me",
        "agent_tone": conversation.get("agent_tone") or "auto",
        "agent_name": conversation.get("agent_name"),
        "agent_style_source_id": conversation.get("agent_style_source_id"),
        "messages_json": _protect_messages(conversation_user_id, conversation["messages"]),
    }
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(agent_conversations.c.id).where(agent_conversations.c.id == conversation["id"])
        ).first()
        if existing:
            connection.execute(
                agent_conversations.update()
                .where(agent_conversations.c.id == conversation["id"])
                .values(**_owned_update_values(payload, "user_id"), updated_at=func.now())
            )
        else:
            connection.execute(agent_conversations.insert().values(**payload))


def get_conversation(conversation_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    statement = select(agent_conversations).where(agent_conversations.c.id == conversation_id)
    if user_id is not None:
        statement = statement.where(agent_conversations.c.user_id == user_id)

    with ENGINE.begin() as connection:
        row = connection.execute(statement).mappings().first()
    if not row:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "agent_provider": row.get("agent_provider"),
        "agent_model": row.get("agent_model"),
        "agent_mode": row.get("agent_mode") or "know_me",
        "agent_tone": row.get("agent_tone") or "auto",
        "agent_name": row.get("agent_name"),
        "agent_style_source_id": row.get("agent_style_source_id"),
        "messages": _unprotect_messages(row["user_id"], row["messages_json"]),
    }


def list_conversations(user_id: str | None = None) -> list[dict[str, Any]]:
    statement = select(agent_conversations).order_by(agent_conversations.c.updated_at.desc())
    if user_id is not None:
        statement = statement.where(agent_conversations.c.user_id == user_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()

    return [
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "status": row["status"],
            "agent_provider": row.get("agent_provider"),
            "agent_model": row.get("agent_model"),
            "agent_mode": row.get("agent_mode") or "know_me",
            "agent_tone": row.get("agent_tone") or "auto",
            "agent_name": row.get("agent_name"),
            "agent_style_source_id": row.get("agent_style_source_id"),
            "messages": _unprotect_messages(row["user_id"], row["messages_json"]),
            "created_at": _isoformat_utc(row["created_at"]),
            "updated_at": _isoformat_utc(row["updated_at"]),
        }
        for row in rows
    ]


def delete_conversation(conversation_id: str, user_id: str | None = None) -> bool:
    statement = select(agent_conversations.c.id).where(agent_conversations.c.id == conversation_id)
    if user_id is not None:
        statement = statement.where(agent_conversations.c.user_id == user_id)

    with ENGINE.begin() as connection:
        existing = connection.execute(statement).first()
        if not existing:
            return False

        connection.execute(
            agent_usage_events.delete().where(agent_usage_events.c.conversation_id == conversation_id)
        )
        connection.execute(
            agent_message_feedback.delete().where(
                agent_message_feedback.c.conversation_id == conversation_id
            )
        )
        connection.execute(
            agent_context_snapshots.delete().where(
                agent_context_snapshots.c.conversation_id == conversation_id
            )
        )
        connection.execute(
            agent_trace_steps.delete().where(
                agent_trace_steps.c.conversation_id == conversation_id
            )
        )
        connection.execute(
            agent_traces.delete().where(agent_traces.c.conversation_id == conversation_id)
        )
        connection.execute(
            agent_conversations.delete().where(agent_conversations.c.id == conversation_id)
        )
    return True

