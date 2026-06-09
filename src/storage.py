from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, create_engine, func, select
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
    Column("messages_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
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
        "messages": row["messages_json"],
    }
