from __future__ import annotations

import os
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
    Column("status", String, nullable=False),
    Column("submission_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_conversations = Table(
    "agent_conversations",
    metadata,
    Column("id", String, primary_key=True),
    Column("status", String, nullable=False),
    Column("agent_provider", String, nullable=True),
    Column("agent_model", String, nullable=True),
    Column("messages_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_usage_events = Table(
    "agent_usage_events",
    metadata,
    Column("id", String, primary_key=True),
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
    Column("conversation_id", String, nullable=False),
    Column("source_type", String, nullable=False),
    Column("title", String, nullable=False),
    Column("content", String, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


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
    _ensure_agent_conversation_columns()


def reset_db() -> None:
    metadata.drop_all(ENGINE)
    metadata.create_all(ENGINE)


def save_draft(draft: dict[str, Any]) -> None:
    payload = {
        "id": draft["id"],
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
                .values(
                    status=payload["status"],
                    submission_json=payload["submission_json"],
                    updated_at=func.now(),
                )
            )
        else:
            connection.execute(draft_profiles.insert().values(**payload))


def get_draft(draft_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(draft_profiles).where(draft_profiles.c.id == draft_id)
        ).mappings().first()
    if not row:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "submission": row["submission_json"],
    }


def save_conversation(conversation: dict[str, Any]) -> None:
    payload = {
        "id": conversation["id"],
        "status": conversation["status"],
        "agent_provider": conversation.get("agent_provider"),
        "agent_model": conversation.get("agent_model"),
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
                .values(
                    status=payload["status"],
                    agent_provider=payload["agent_provider"],
                    agent_model=payload["agent_model"],
                    messages_json=payload["messages_json"],
                    updated_at=func.now(),
                )
            )
        else:
            connection.execute(agent_conversations.insert().values(**payload))


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(agent_conversations).where(agent_conversations.c.id == conversation_id)
        ).mappings().first()
    if not row:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "agent_provider": row.get("agent_provider"),
        "agent_model": row.get("agent_model"),
        "messages": row["messages_json"],
    }


def _ensure_agent_conversation_columns() -> None:
    existing_columns = {
        column["name"] for column in inspect(ENGINE).get_columns("agent_conversations")
    }
    missing_columns = [
        column_name
        for column_name in ("agent_provider", "agent_model")
        if column_name not in existing_columns
    ]
    if not missing_columns:
        return

    with ENGINE.begin() as connection:
        for column_name in missing_columns:
            connection.execute(text(f"ALTER TABLE agent_conversations ADD COLUMN {column_name} VARCHAR"))


def save_agent_usage_event(event: dict[str, Any]) -> None:
    payload = {
        "id": event.get("id") or str(uuid4()),
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


def list_agent_usage_events(conversation_id: str | None = None) -> list[dict[str, Any]]:
    statement = select(agent_usage_events).order_by(agent_usage_events.c.created_at.desc())
    if conversation_id:
        statement = statement.where(agent_usage_events.c.conversation_id == conversation_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()

    return [
        {
            "id": row["id"],
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
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


def summarize_agent_usage(conversation_id: str | None = None) -> dict[str, Any]:
    events = list_agent_usage_events(conversation_id)
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


def list_context_sources(conversation_id: str) -> list[dict[str, Any]]:
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(conversation_context_sources)
            .where(conversation_context_sources.c.conversation_id == conversation_id)
            .order_by(conversation_context_sources.c.created_at.desc())
        ).mappings().all()
    return [_context_source_from_row(row) for row in rows]


def _context_source_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "source_type": row["source_type"],
        "title": row["title"],
        "content": row["content"],
        "metadata": row["metadata_json"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
