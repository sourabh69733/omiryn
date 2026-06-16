from __future__ import annotations

import os
from datetime import timezone
from uuid import uuid4
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Engine

DEFAULT_DATABASE_URL = "sqlite:///./data/omiryn.db"

metadata = MetaData()

draft_profiles = Table(
    "draft_profiles",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("status", String, nullable=False),
    Column("submission_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_conversations = Table(
    "agent_conversations",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("status", String, nullable=False),
    Column("agent_provider", String, nullable=True),
    Column("agent_model", String, nullable=True),
    Column("agent_mode", String, nullable=True),
    Column("agent_tone", String, nullable=True),
    Column("agent_style_source_id", String, nullable=True),
    Column("messages_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_usage_events = Table(
    "agent_usage_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=True),
    Column("request_kind", String, nullable=False),
    Column("provider", String, nullable=False),
    Column("model", String, nullable=True),
    Column("success", Boolean, nullable=False),
    Column("prompt_tokens", Integer, nullable=True),
    Column("completion_tokens", Integer, nullable=True),
    Column("total_tokens", Integer, nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("estimated_cost_usd", Float, nullable=True),
    Column("error", String, nullable=True),
    Column("raw_usage_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

conversation_context_sources = Table(
    "conversation_context_sources",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("source_type", String, nullable=False),
    Column("title", String, nullable=False),
    Column("content", String, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

user_profiles = Table(
    "user_profiles",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("display_name", String, nullable=True),
    Column("gender", String, nullable=True),
    Column("interested_in", String, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


def database_url() -> str:
    return _normalize_database_url(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def engine() -> Engine:
    url = database_url()
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        if db_path.parent != Path("."):
            db_path.parent.mkdir(parents=True, exist_ok=True)

    return create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )


ENGINE = engine()


def init_db() -> None:
    metadata.create_all(ENGINE)
    _ensure_runtime_columns()


def reset_db() -> None:
    metadata.drop_all(ENGINE)
    metadata.create_all(ENGINE)


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
    payload = {
        "id": conversation["id"],
        "user_id": user_id,
        "status": conversation["status"],
        "agent_provider": conversation.get("agent_provider"),
        "agent_model": conversation.get("agent_model"),
        "agent_mode": conversation.get("agent_mode") or "know_me",
        "agent_tone": conversation.get("agent_tone") or "auto",
        "agent_style_source_id": conversation.get("agent_style_source_id"),
        "messages_json": conversation["messages"],
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
        "agent_style_source_id": row.get("agent_style_source_id"),
        "messages": row["messages_json"],
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
            "agent_style_source_id": row.get("agent_style_source_id"),
            "messages": row["messages_json"],
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
            conversation_context_sources.delete().where(
                conversation_context_sources.c.conversation_id == conversation_id
            )
        )
        connection.execute(
            agent_usage_events.delete().where(agent_usage_events.c.conversation_id == conversation_id)
        )
        connection.execute(
            agent_conversations.delete().where(agent_conversations.c.id == conversation_id)
        )
    return True


def _ensure_runtime_columns() -> None:
    required_columns = {
        "user_profiles": ("display_name", "gender", "interested_in"),
        "draft_profiles": ("user_id",),
        "agent_usage_events": ("user_id",),
        "conversation_context_sources": ("user_id",),
        "agent_conversations": (
            "user_id",
            "agent_provider",
            "agent_model",
            "agent_mode",
            "agent_tone",
            "agent_style_source_id",
        ),
    }
    with ENGINE.begin() as connection:
        for table_name, column_names in required_columns.items():
            existing_columns = {column["name"] for column in inspect(ENGINE).get_columns(table_name)}
            for column_name in column_names:
                if column_name not in existing_columns:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR"))


def save_agent_usage_event(event: dict[str, Any]) -> None:
    user_id = event.get("user_id") or _conversation_user_id(event.get("conversation_id"))
    payload = {
        "id": event.get("id") or str(uuid4()),
        "user_id": user_id,
        "conversation_id": event.get("conversation_id"),
        "request_kind": event["request_kind"],
        "provider": event["provider"],
        "model": event.get("model"),
        "success": event["success"],
        "prompt_tokens": event.get("prompt_tokens"),
        "completion_tokens": event.get("completion_tokens"),
        "total_tokens": event.get("total_tokens"),
        "latency_ms": event.get("latency_ms"),
        "estimated_cost_usd": event.get("estimated_cost_usd"),
        "error": event.get("error"),
        "raw_usage_json": event.get("raw_usage") or {},
    }
    with ENGINE.begin() as connection:
        connection.execute(agent_usage_events.insert().values(**payload))


def get_user_profile(user_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(user_profiles).where(user_profiles.c.user_id == user_id)
        ).mappings().first()
    if not row:
        return None
    return {
        "user_id": row["user_id"],
        "display_name": row["display_name"],
        "gender": row["gender"],
        "interested_in": row["interested_in"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def save_user_profile(
    user_id: str,
    gender: str,
    interested_in: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    payload = {
        "user_id": user_id,
        "display_name": display_name,
        "gender": gender,
        "interested_in": interested_in,
    }
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(user_profiles.c.user_id).where(user_profiles.c.user_id == user_id)
        ).first()
        if existing:
            connection.execute(
                user_profiles.update()
                .where(user_profiles.c.user_id == user_id)
                .values(
                    **_owned_update_values(payload, "display_name"),
                    updated_at=func.now(),
                )
            )
        else:
            connection.execute(user_profiles.insert().values(**payload))

    return get_user_profile(user_id) or payload


def list_user_context_sources(
    user_id: str,
    source_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(conversation_context_sources)
        .where(conversation_context_sources.c.user_id == user_id)
        .order_by(conversation_context_sources.c.created_at.desc())
    )
    if source_types:
        statement = statement.where(conversation_context_sources.c.source_type.in_(source_types))

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_context_source_from_row(row) for row in rows]


def list_agent_usage_events(
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(agent_usage_events).order_by(agent_usage_events.c.created_at.desc())
    if conversation_id:
        statement = statement.where(agent_usage_events.c.conversation_id == conversation_id)
    if user_id is not None:
        statement = statement.where(agent_usage_events.c.user_id == user_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()

    return [
        {
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
        for row in rows
    ]


def summarize_agent_usage(
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    events = list_agent_usage_events(conversation_id, user_id)
    successful_events = [event for event in events if event["success"]]
    estimated_cost_usd = round(
        sum(event["estimated_cost_usd"] or 0 for event in events),
        8,
    )
    return {
        "conversation_id": conversation_id,
        "request_count": len(events),
        "successful_request_count": len(successful_events),
        "failed_request_count": len(events) - len(successful_events),
        "prompt_tokens": sum(event["prompt_tokens"] or 0 for event in events),
        "completion_tokens": sum(event["completion_tokens"] or 0 for event in events),
        "total_tokens": sum(event["total_tokens"] or 0 for event in events),
        "estimated_cost_usd": estimated_cost_usd,
        "estimated_cost_inr": _estimated_cost_inr(estimated_cost_usd),
    }


def _estimated_cost_inr(estimated_cost_usd: float) -> float | None:
    usd_to_inr = float(os.getenv("USD_TO_INR", "0") or 0)
    if usd_to_inr == 0:
        return None
    return round(estimated_cost_usd * usd_to_inr, 6)


def save_context_source(source: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": source.get("id") or str(uuid4()),
        "user_id": source.get("user_id") or _conversation_user_id(source["conversation_id"]),
        "conversation_id": source["conversation_id"],
        "source_type": source["source_type"],
        "title": source["title"],
        "content": source["content"],
        "metadata_json": source.get("metadata") or {},
    }
    with ENGINE.begin() as connection:
        connection.execute(conversation_context_sources.insert().values(**payload))
        row = connection.execute(
            select(conversation_context_sources).where(
                conversation_context_sources.c.id == payload["id"]
            )
        ).mappings().first()
    return _context_source_from_row(row)


def list_context_sources(conversation_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    statement = (
        select(conversation_context_sources)
        .where(conversation_context_sources.c.conversation_id == conversation_id)
        .order_by(conversation_context_sources.c.created_at.desc())
    )
    if user_id is not None:
        statement = statement.where(conversation_context_sources.c.user_id == user_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_context_source_from_row(row) for row in rows]


def _context_source_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "source_type": row["source_type"],
        "title": row["title"],
        "content": row["content"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _owned_update_values(payload: dict[str, Any], owner_key: str) -> dict[str, Any]:
    values = {key: value for key, value in payload.items() if key != "id"}
    if values.get(owner_key) is None:
        values.pop(owner_key, None)
    return values


def _conversation_user_id(conversation_id: str | None) -> str | None:
    if not conversation_id:
        return None
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(agent_conversations.c.user_id).where(
                agent_conversations.c.id == conversation_id
            )
        ).first()
    return row[0] if row else None


def _isoformat_utc(value: Any) -> str | None:
    if not value:
        return None
    if value.tzinfo is None:
        return f"{value.isoformat()}Z"
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
