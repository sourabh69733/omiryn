from __future__ import annotations

import json
import os
from datetime import timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

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
from sqlalchemy.engine.url import make_url
from sqlalchemy.pool import NullPool

from security.encryption import (
    decrypt_json,
    decrypt_text,
    is_encrypted_blob,
    maybe_encrypt_json,
    maybe_encrypt_text,
)

DEFAULT_DATABASE_URL = "sqlite:///./data/omiryn.db"

# Vercel/serverless should not keep an application-side SQLAlchemy pool.
DB_DISABLE_POOL="false"

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
    Column("agent_name", String, nullable=True),
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

agent_context_snapshots = Table(
    "agent_context_snapshots",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("message_index", Integer, nullable=False),
    Column("summary_json", JSON, nullable=False),
    Column("context_json", JSON, nullable=False),
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

whatsapp_imports = Table(
    "whatsapp_imports",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("context_source_id", String, nullable=False),
    Column("style_kind", String, nullable=False),
    Column("title", String, nullable=False),
    Column("selected_sender", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

whatsapp_messages = Table(
    "whatsapp_messages",
    metadata,
    Column("id", String, primary_key=True),
    Column("import_id", String, nullable=False),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("message_index", Integer, nullable=False),
    Column("sender", String, nullable=False),
    Column("timestamp_text", String, nullable=True),
    Column("content", String, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

whatsapp_chunks = Table(
    "whatsapp_chunks",
    metadata,
    Column("id", String, primary_key=True),
    Column("import_id", String, nullable=False),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("chunk_index", Integer, nullable=False),
    Column("start_message_index", Integer, nullable=False),
    Column("end_message_index", Integer, nullable=False),
    Column("content", String, nullable=False),
    Column("terms_json", JSON, nullable=False),
    Column("embedding_json", JSON, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

whatsapp_people = Table(
    "whatsapp_people",
    metadata,
    Column("id", String, primary_key=True),
    Column("import_id", String, nullable=False),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("sender", String, nullable=False),
    Column("message_count", Integer, nullable=False),
    Column("role", String, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

whatsapp_style_profiles = Table(
    "whatsapp_style_profiles",
    metadata,
    Column("id", String, primary_key=True),
    Column("import_id", String, nullable=False),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("sender", String, nullable=False),
    Column("summary_json", JSON, nullable=False),
    Column("sample_messages_json", JSON, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

user_profiles = Table(
    "user_profiles",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("display_name", String, nullable=True),
    Column("age", Integer, nullable=True),
    Column("gender", String, nullable=True),
    Column("interested_in", String, nullable=True),
    Column("city", String, nullable=True),
    Column("phone", String, nullable=True),
    Column("profile_photo_url", String, nullable=True),
    Column("profile_photo_urls", JSON, nullable=True),
    Column("profile_photo_file_name", String, nullable=True),
    Column("profile_photo_file_names", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

profile_facts = Table(
    "profile_facts",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("category", String, nullable=False),
    Column("key", String, nullable=False),
    Column("value_json", JSON, nullable=False),
    Column("label", String, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("source_kind", String, nullable=False),
    Column("source_id", String, nullable=True),
    Column("evidence_json", JSON, nullable=False),
    Column("status", String, nullable=False),
    Column("visibility", String, nullable=False),
    Column("used_for_matching", Boolean, nullable=False),
    Column("used_for_chat_context", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

data_point_feedback = Table(
    "data_point_feedback",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("profile_fact_id", String, nullable=False),
    Column("rating", String, nullable=False),
    Column("reason", String, nullable=True),
    Column("comment", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

data_point_extraction_debug = Table(
    "data_point_extraction_debug",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("source_kind", String, nullable=False),
    Column("source_id", String, nullable=True),
    Column("import_id", String, nullable=True),
    Column("candidate_key", String, nullable=True),
    Column("decision", String, nullable=False),
    Column("candidate_json", JSON, nullable=False),
    Column("review_json", JSON, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_message_feedback = Table(
    "agent_message_feedback",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=True),
    Column("conversation_id", String, nullable=False),
    Column("message_index", Integer, nullable=False),
    Column("rating", String, nullable=False),
    Column("reason", String, nullable=True),
    Column("comment", String, nullable=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
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

    connect_args: dict[str, Any] = {}
    engine_args: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    else:
        connect_args["prepare_threshold"] = None
        if _disable_application_pool():
            engine_args["poolclass"] = NullPool

    return create_engine(url, connect_args=connect_args, **engine_args)


def _disable_application_pool() -> bool:
    return DB_DISABLE_POOL == "true"


ENGINE = engine()


def init_db() -> None:
    metadata.create_all(ENGINE)
    _ensure_runtime_columns()


def reset_db() -> None:
    if not _reset_db_allowed(database_url()):
        raise RuntimeError(
            "Refusing to reset a non-test database. "
            "Use a DATABASE_URL with a test database name/path, or set "
            "OMIRYN_ALLOW_RESET_DB=true for an intentional manual reset."
        )
    metadata.drop_all(ENGINE)
    metadata.create_all(ENGINE)


def _reset_db_allowed(url: str) -> bool:
    if os.getenv("OMIRYN_ALLOW_RESET_DB", "").lower() == "true":
        return True
    parsed = make_url(url)
    if parsed.drivername.startswith("sqlite"):
        database = parsed.database or ""
        return "test" in Path(database).name.lower()
    return "test" in (parsed.database or "").lower()


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
            agent_conversations.delete().where(agent_conversations.c.id == conversation_id)
        )
    return True


def _ensure_runtime_columns() -> None:
    required_columns = {
        "user_profiles": (
            "display_name",
            "age",
            "gender",
            "interested_in",
            "city",
            "phone",
            "profile_photo_url",
            "profile_photo_urls",
            "profile_photo_file_name",
            "profile_photo_file_names",
        ),
        "draft_profiles": ("user_id",),
        "agent_usage_events": ("user_id",),
        "conversation_context_sources": ("user_id",),
        "profile_facts": ("used_for_chat_context",),
        "agent_conversations": (
            "user_id",
            "agent_provider",
            "agent_model",
            "agent_mode",
            "agent_tone",
            "agent_name",
            "agent_style_source_id",
        ),
    }
    with ENGINE.begin() as connection:
        for table_name, column_names in required_columns.items():
            existing_columns = {column["name"] for column in inspect(ENGINE).get_columns(table_name)}
            for column_name in column_names:
                if column_name not in existing_columns:
                    column_type = "BOOLEAN" if column_name == "used_for_chat_context" else "VARCHAR"
                    if column_name == "age":
                        column_type = "INTEGER"
                    if column_name in {"profile_photo_urls", "profile_photo_file_names"}:
                        column_type = "JSON"
                    default = " DEFAULT FALSE" if column_name == "used_for_chat_context" else ""
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {column_name} {column_type}{default}"
                        )
                    )


def upsert_profile_fact(fact: dict[str, Any]) -> dict[str, Any]:
    payload = _profile_fact_payload(fact)
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(profile_facts).where(
                profile_facts.c.user_id == payload["user_id"],
                profile_facts.c.category == payload["category"],
                profile_facts.c.key == payload["key"],
            )
        ).mappings().first()
        if existing:
            merged = _merge_profile_fact(existing, payload)
            connection.execute(
                profile_facts.update()
                .where(profile_facts.c.id == existing["id"])
                .values(**merged, updated_at=func.now())
            )
            fact_id = existing["id"]
        else:
            fact_id = payload["id"]
            connection.execute(profile_facts.insert().values(**payload))

        row = connection.execute(
            select(profile_facts).where(profile_facts.c.id == fact_id)
        ).mappings().first()
    return _profile_fact_from_row(row)


def list_profile_facts(
    user_id: str,
    statuses: set[str] | None = None,
    used_for_matching: bool | None = None,
    used_for_chat_context: bool | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(profile_facts)
        .where(profile_facts.c.user_id == user_id)
        .order_by(
            profile_facts.c.category.asc(),
            profile_facts.c.confidence.desc(),
            profile_facts.c.updated_at.desc(),
        )
    )
    if statuses:
        statement = statement.where(profile_facts.c.status.in_(statuses))
    if used_for_matching is not None:
        statement = statement.where(profile_facts.c.used_for_matching == used_for_matching)
    if used_for_chat_context is not None:
        statement = statement.where(profile_facts.c.used_for_chat_context == used_for_chat_context)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return _dedupe_profile_fact_dicts([_profile_fact_from_row(row) for row in rows])


def delete_profile_facts_by_source(
    source_kind: str,
    source_ids: list[str],
    user_id: str | None = None,
) -> int:
    if not source_ids:
        return 0
    select_statement = select(profile_facts.c.id).where(
        profile_facts.c.source_kind == source_kind,
        profile_facts.c.source_id.in_(source_ids),
    )
    if user_id is not None:
        select_statement = select_statement.where(profile_facts.c.user_id == user_id)
    statement = profile_facts.delete().where(
        profile_facts.c.source_kind == source_kind,
        profile_facts.c.source_id.in_(source_ids),
    )
    if user_id is not None:
        statement = statement.where(profile_facts.c.user_id == user_id)
    with ENGINE.begin() as connection:
        fact_ids = [row[0] for row in connection.execute(select_statement).all()]
        if fact_ids:
            connection.execute(
                data_point_feedback.delete().where(
                    data_point_feedback.c.profile_fact_id.in_(fact_ids)
                )
            )
        result = connection.execute(statement)
    return int(result.rowcount or 0)


def get_profile_fact(fact_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    statement = select(profile_facts).where(profile_facts.c.id == fact_id)
    if user_id is not None:
        statement = statement.where(profile_facts.c.user_id == user_id)

    with ENGINE.begin() as connection:
        row = connection.execute(statement).mappings().first()
    return _profile_fact_from_row(row) if row else None


def save_data_point_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": feedback.get("id") or str(uuid4()),
        "user_id": feedback["user_id"],
        "profile_fact_id": feedback["profile_fact_id"],
        "rating": feedback["rating"],
        "reason": feedback.get("reason"),
        "comment": feedback.get("comment"),
        "metadata_json": feedback.get("metadata") or {},
    }
    with ENGINE.begin() as connection:
        existing = connection.execute(
            select(data_point_feedback).where(
                data_point_feedback.c.user_id == payload["user_id"],
                data_point_feedback.c.profile_fact_id == payload["profile_fact_id"],
            )
        ).mappings().first()
        if existing:
            feedback_id = existing["id"]
            connection.execute(
                data_point_feedback.update()
                .where(data_point_feedback.c.id == feedback_id)
                .values(
                    rating=payload["rating"],
                    reason=payload["reason"],
                    comment=payload["comment"],
                    metadata_json=payload["metadata_json"],
                    updated_at=func.now(),
                )
            )
        else:
            feedback_id = payload["id"]
            connection.execute(data_point_feedback.insert().values(**payload))

        row = connection.execute(
            select(data_point_feedback).where(data_point_feedback.c.id == feedback_id)
        ).mappings().first()
    return _data_point_feedback_from_row(row)


def list_data_point_feedback(
    user_id: str | None = None,
    profile_fact_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(data_point_feedback).order_by(data_point_feedback.c.updated_at.desc())
    if user_id is not None:
        statement = statement.where(data_point_feedback.c.user_id == user_id)
    if profile_fact_id is not None:
        statement = statement.where(data_point_feedback.c.profile_fact_id == profile_fact_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_data_point_feedback_from_row(row) for row in rows]


def save_data_point_extraction_debug(entry: dict[str, Any]) -> dict[str, Any]:
    user_id = entry.get("user_id")
    payload = {
        "id": entry.get("id") or str(uuid4()),
        "user_id": user_id,
        "source_kind": entry.get("source_kind") or "unknown",
        "source_id": entry.get("source_id"),
        "import_id": entry.get("import_id"),
        "candidate_key": entry.get("candidate_key"),
        "decision": str(entry.get("decision") or "unknown"),
        "candidate_json": maybe_encrypt_json(user_id, entry.get("candidate") or {}),
        "review_json": maybe_encrypt_json(user_id, entry.get("review") or {}),
        "metadata_json": maybe_encrypt_json(user_id, entry.get("metadata") or {}),
    }
    with ENGINE.begin() as connection:
        connection.execute(data_point_extraction_debug.insert().values(**payload))
        row = connection.execute(
            select(data_point_extraction_debug).where(
                data_point_extraction_debug.c.id == payload["id"]
            )
        ).mappings().first()
    return _data_point_extraction_debug_from_row(row)


def list_data_point_extraction_debug(
    user_id: str | None = None,
    source_id: str | None = None,
    import_id: str | None = None,
    decision: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    statement = select(data_point_extraction_debug).order_by(
        data_point_extraction_debug.c.created_at.desc()
    )
    if user_id is not None:
        statement = statement.where(data_point_extraction_debug.c.user_id == user_id)
    if source_id is not None:
        statement = statement.where(data_point_extraction_debug.c.source_id == source_id)
    if import_id is not None:
        statement = statement.where(data_point_extraction_debug.c.import_id == import_id)
    if decision is not None:
        statement = statement.where(data_point_extraction_debug.c.decision == decision)
    if limit is not None:
        statement = statement.limit(limit)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_data_point_extraction_debug_from_row(row) for row in rows]


def _profile_fact_payload(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": fact.get("id") or str(uuid4()),
        "user_id": fact["user_id"],
        "category": fact["category"],
        "key": fact["key"],
        "value_json": fact.get("value") or fact.get("value_json") or {},
        "label": fact["label"],
        "confidence": _bounded_confidence(fact.get("confidence", 0.5)),
        "source_kind": fact.get("source_kind") or "agent_chat",
        "source_id": fact.get("source_id"),
        "evidence_json": _normalize_evidence_items(
            fact.get("evidence") or fact.get("evidence_json") or []
        ),
        "status": fact.get("status") or "active",
        "visibility": fact.get("visibility") or "internal",
        "used_for_matching": bool(fact.get("used_for_matching", True)),
        "used_for_chat_context": bool(fact.get("used_for_chat_context", False)),
    }


def _merge_profile_fact(existing: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    evidence = _dedupe_evidence(
        list(existing["evidence_json"] or []) + list(incoming["evidence_json"] or [])
    )
    return {
        "value_json": incoming["value_json"],
        "label": incoming["label"],
        "confidence": max(existing["confidence"] or 0, incoming["confidence"]),
        "source_kind": incoming["source_kind"],
        "source_id": incoming["source_id"] or existing["source_id"],
        "evidence_json": evidence,
        "status": incoming["status"] or existing["status"],
        "visibility": incoming["visibility"] or existing["visibility"],
        "used_for_matching": incoming["used_for_matching"],
        "used_for_chat_context": incoming["used_for_chat_context"],
    }


def _dedupe_evidence(evidence_items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    deduped: list[Any] = []
    for item in _normalize_evidence_items(evidence_items):
        key = repr(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_evidence_items(evidence_items: list[Any]) -> list[Any]:
    normalized_items = []
    for item in evidence_items:
        if not isinstance(item, dict):
            normalized_items.append(item)
            continue
        normalized = dict(item)
        text = str(normalized.get("text") or normalized.get("quote") or "").strip()
        if text:
            normalized["text"] = text
            normalized["quote"] = text
        normalized_items.append(normalized)
    return normalized_items


def _dedupe_profile_fact_dicts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for fact in facts:
        identity = _profile_fact_identity(fact)
        existing = deduped.get(identity)
        if not existing:
            deduped[identity] = fact
            continue
        deduped[identity] = _merge_profile_fact_dict(existing, fact)
    return list(deduped.values())


def _merge_profile_fact_dict(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if float(incoming.get("confidence") or 0) > float(existing.get("confidence") or 0):
        base = {**existing, **incoming}
    else:
        base = dict(existing)
    base["confidence"] = max(
        float(existing.get("confidence") or 0),
        float(incoming.get("confidence") or 0),
    )
    base["evidence"] = _dedupe_evidence(
        list(existing.get("evidence") or []) + list(incoming.get("evidence") or [])
    )
    return base


def _profile_fact_identity(fact: dict[str, Any]) -> tuple[str, str]:
    user_id = str(fact.get("user_id") or "")
    category = _normalized_fact_terms(str(fact.get("category") or ""))
    label_terms = _normalized_fact_terms(str(fact.get("label") or ""))
    value_terms = _normalized_fact_terms(_fact_value_text(fact.get("value")))
    key_terms = _normalized_fact_terms(str(fact.get("key") or ""))
    meaning = label_terms or value_terms or key_terms
    return user_id, f"{category}:{meaning}"


def _fact_value_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(part) for part in value.values())
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return str(value or "")


def _normalized_fact_terms(text_value: str) -> str:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "be",
        "for",
        "has",
        "is",
        "of",
        "the",
        "to",
        "use",
        "uses",
        "using",
        "with",
    }
    words = [
        _singularize_token(token)
        for token in "".join(
            character.lower() if character.isalnum() else " " for character in text_value
        ).split()
        if token not in stopwords
    ]
    return "_".join(sorted(dict.fromkeys(words)))


def _singularize_token(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _bounded_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.5
    return max(0.0, min(1.0, confidence))


def _profile_fact_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "category": row["category"],
        "key": row["key"],
        "value": row["value_json"],
        "label": row["label"],
        "confidence": row["confidence"],
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "evidence": row["evidence_json"],
        "status": row["status"],
        "visibility": row["visibility"],
        "used_for_matching": row["used_for_matching"],
        "used_for_chat_context": row["used_for_chat_context"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def _data_point_feedback_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "profile_fact_id": row["profile_fact_id"],
        "rating": row["rating"],
        "reason": row["reason"],
        "comment": row["comment"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def _data_point_extraction_debug_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "import_id": row["import_id"],
        "candidate_key": row["candidate_key"],
        "decision": row["decision"],
        "candidate": decrypt_json(row["user_id"], row["candidate_json"]),
        "review": decrypt_json(row["user_id"], row["review_json"]),
        "metadata": decrypt_json(row["user_id"], row["metadata_json"]),
        "created_at": _isoformat_utc(row["created_at"]),
    }


def save_agent_message_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": feedback.get("id") or str(uuid4()),
        "user_id": feedback.get("user_id"),
        "conversation_id": feedback["conversation_id"],
        "message_index": feedback["message_index"],
        "rating": feedback["rating"],
        "reason": feedback.get("reason"),
        "comment": feedback.get("comment"),
        "metadata_json": feedback.get("metadata") or {},
    }
    with ENGINE.begin() as connection:
        connection.execute(agent_message_feedback.insert().values(**payload))
        row = connection.execute(
            select(agent_message_feedback).where(agent_message_feedback.c.id == payload["id"])
        ).mappings().first()
    return _agent_message_feedback_from_row(row)


def list_agent_message_feedback(
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(agent_message_feedback).order_by(agent_message_feedback.c.created_at.desc())
    if conversation_id:
        statement = statement.where(agent_message_feedback.c.conversation_id == conversation_id)
    if user_id is not None:
        statement = statement.where(agent_message_feedback.c.user_id == user_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_agent_message_feedback_from_row(row) for row in rows]


def _agent_message_feedback_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "message_index": row["message_index"],
        "rating": row["rating"],
        "reason": row["reason"],
        "comment": row["comment"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


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


def save_agent_context_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    user_id = snapshot.get("user_id") or _conversation_user_id(snapshot.get("conversation_id"))
    payload = {
        "id": snapshot.get("id") or str(uuid4()),
        "user_id": user_id,
        "conversation_id": snapshot["conversation_id"],
        "message_index": snapshot["message_index"],
        "summary_json": maybe_encrypt_json(user_id, snapshot.get("summary") or {}),
        "context_json": maybe_encrypt_json(user_id, snapshot.get("context") or {}),
    }
    with ENGINE.begin() as connection:
        connection.execute(agent_context_snapshots.insert().values(**payload))
        row = connection.execute(
            select(agent_context_snapshots).where(agent_context_snapshots.c.id == payload["id"])
        ).mappings().first()
    return _agent_context_snapshot_from_row(row)


def list_agent_context_snapshots(
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(agent_context_snapshots).order_by(
        agent_context_snapshots.c.created_at.desc()
    )
    if conversation_id:
        statement = statement.where(agent_context_snapshots.c.conversation_id == conversation_id)
    if user_id is not None:
        statement = statement.where(agent_context_snapshots.c.user_id == user_id)

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_agent_context_snapshot_from_row(row) for row in rows]


def _agent_context_snapshot_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "message_index": row["message_index"],
        "summary": decrypt_json(row["user_id"], row["summary_json"]),
        "context": decrypt_json(row["user_id"], row["context_json"]),
        "created_at": _isoformat_utc(row["created_at"]),
    }


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
        "age": row["age"],
        "gender": row["gender"],
        "interested_in": row["interested_in"],
        "city": row["city"],
        "phone": row["phone"],
        "profile_photo_url": row["profile_photo_url"],
        "profile_photo_urls": row["profile_photo_urls"] or [],
        "profile_photo_file_name": row["profile_photo_file_name"],
        "profile_photo_file_names": row["profile_photo_file_names"] or [],
        "created_at": _isoformat_utc(row["created_at"]),
        "updated_at": _isoformat_utc(row["updated_at"]),
    }


def save_user_profile(
    user_id: str,
    gender: str,
    interested_in: str,
    display_name: str | None = None,
    age: int | None = None,
    city: str | None = None,
    phone: str | None = None,
    profile_photo_url: str | None = None,
    profile_photo_urls: list[str] | None = None,
    profile_photo_file_name: str | None = None,
    profile_photo_file_names: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "user_id": user_id,
        "display_name": display_name,
        "age": age,
        "gender": gender,
        "interested_in": interested_in,
        "city": city,
        "phone": phone,
        "profile_photo_url": profile_photo_url,
        "profile_photo_urls": profile_photo_urls or ([profile_photo_url] if profile_photo_url else []),
        "profile_photo_file_name": profile_photo_file_name,
        "profile_photo_file_names": profile_photo_file_names
        or ([profile_photo_file_name] if profile_photo_file_name else []),
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
    successful_chat_events = [
        event for event in successful_events if event["request_kind"] == "chat_reply"
    ]
    chat_message_count = len(successful_chat_events)
    chat_prompt_tokens = sum(event["prompt_tokens"] or 0 for event in successful_chat_events)
    chat_completion_tokens = sum(
        event["completion_tokens"] or 0 for event in successful_chat_events
    )
    chat_total_tokens = sum(event["total_tokens"] or 0 for event in successful_chat_events)
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
        "chat_message_count": chat_message_count,
        "average_tokens_per_message": _average_int(chat_total_tokens, chat_message_count),
        "average_prompt_tokens_per_message": _average_int(chat_prompt_tokens, chat_message_count),
        "average_completion_tokens_per_message": _average_int(
            chat_completion_tokens,
            chat_message_count,
        ),
        "estimated_cost_usd": estimated_cost_usd,
        "estimated_cost_inr": _estimated_cost_inr(estimated_cost_usd),
    }


def _average_int(total: int, count: int) -> int:
    if count <= 0:
        return 0
    return round(total / count)


def _estimated_cost_inr(estimated_cost_usd: float) -> float | None:
    usd_to_inr = float(os.getenv("USD_TO_INR", "0") or 0)
    if usd_to_inr == 0:
        return None
    return round(estimated_cost_usd * usd_to_inr, 6)


def save_context_source(source: dict[str, Any]) -> dict[str, Any]:
    source_user_id = source.get("user_id") or _conversation_user_id(source["conversation_id"])
    payload = {
        "id": source.get("id") or str(uuid4()),
        "user_id": source_user_id,
        "conversation_id": source["conversation_id"],
        "source_type": source["source_type"],
        "title": source["title"],
        "content": _protect_text(source_user_id, source["content"]),
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


def save_whatsapp_import_bundle(
    bundle: dict[str, Any],
    user_id: str | None = None,
) -> dict[str, Any]:
    import_id = bundle.get("id") or str(uuid4())
    import_user_id = user_id if user_id is not None else bundle.get("user_id")
    import_payload = {
        "id": import_id,
        "user_id": import_user_id,
        "conversation_id": bundle["conversation_id"],
        "context_source_id": bundle["context_source_id"],
        "style_kind": bundle["style_kind"],
        "title": bundle["title"],
        "selected_sender": bundle.get("selected_sender"),
        "metadata_json": bundle.get("metadata") or {},
    }
    with ENGINE.begin() as connection:
        existing_import_ids = [
            row[0]
            for row in connection.execute(
                select(whatsapp_imports.c.id).where(
                    whatsapp_imports.c.context_source_id == import_payload["context_source_id"]
                )
            ).all()
        ]
        _delete_whatsapp_import_rows(connection, existing_import_ids)
        if existing_import_ids:
            connection.execute(
                whatsapp_imports.delete().where(whatsapp_imports.c.id.in_(existing_import_ids))
            )
        connection.execute(whatsapp_imports.insert().values(**import_payload))

        for index, message in enumerate(bundle.get("messages") or []):
            connection.execute(
                whatsapp_messages.insert().values(
                    id=message.get("id") or str(uuid4()),
                    import_id=import_id,
                    user_id=import_user_id,
                    conversation_id=import_payload["conversation_id"],
                    message_index=message.get("message_index", index),
                    sender=message["sender"],
                    timestamp_text=message.get("timestamp_text"),
                    content=_protect_text(import_user_id, message["content"]),
                    metadata_json=message.get("metadata") or {},
                )
            )

        for chunk in bundle.get("chunks") or []:
            connection.execute(
                whatsapp_chunks.insert().values(
                    id=chunk.get("id") or str(uuid4()),
                    import_id=import_id,
                    user_id=import_user_id,
                    conversation_id=import_payload["conversation_id"],
                    chunk_index=chunk["chunk_index"],
                    start_message_index=chunk["start_message_index"],
                    end_message_index=chunk["end_message_index"],
                    content=_protect_text(import_user_id, chunk["content"]),
                    terms_json=chunk.get("terms") or [],
                    embedding_json=chunk.get("embedding"),
                    metadata_json=chunk.get("metadata") or {},
                )
            )

        for person in bundle.get("people") or []:
            connection.execute(
                whatsapp_people.insert().values(
                    id=person.get("id") or str(uuid4()),
                    import_id=import_id,
                    user_id=import_user_id,
                    conversation_id=import_payload["conversation_id"],
                    sender=person["sender"],
                    message_count=person["message_count"],
                    role=person["role"],
                    metadata_json=person.get("metadata") or {},
                )
            )

        for profile in bundle.get("style_profiles") or []:
            connection.execute(
                whatsapp_style_profiles.insert().values(
                    id=profile.get("id") or str(uuid4()),
                    import_id=import_id,
                    user_id=import_user_id,
                    conversation_id=import_payload["conversation_id"],
                    sender=profile["sender"],
                    summary_json=maybe_encrypt_json(import_user_id, profile.get("summary") or {}),
                    sample_messages_json=maybe_encrypt_json(
                        import_user_id,
                        profile.get("sample_messages") or [],
                    ),
                    metadata_json=profile.get("metadata") or {},
                )
            )

        row = connection.execute(
            select(whatsapp_imports).where(whatsapp_imports.c.id == import_id)
        ).mappings().first()
    return _whatsapp_import_from_row(row)


def list_whatsapp_imports(
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(whatsapp_imports).order_by(whatsapp_imports.c.created_at.desc())
    if conversation_id:
        statement = statement.where(whatsapp_imports.c.conversation_id == conversation_id)
    if user_id is not None:
        statement = statement.where(whatsapp_imports.c.user_id == user_id)
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_whatsapp_import_from_row(row) for row in rows]


def list_whatsapp_messages(import_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    statement = (
        select(whatsapp_messages)
        .where(whatsapp_messages.c.import_id == import_id)
        .order_by(whatsapp_messages.c.message_index.asc())
    )
    if user_id is not None:
        statement = statement.where(whatsapp_messages.c.user_id == user_id)
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_whatsapp_message_from_row(row) for row in rows]


def list_whatsapp_chunks(import_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    statement = (
        select(whatsapp_chunks)
        .where(whatsapp_chunks.c.import_id == import_id)
        .order_by(whatsapp_chunks.c.chunk_index.asc())
    )
    if user_id is not None:
        statement = statement.where(whatsapp_chunks.c.user_id == user_id)
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_whatsapp_chunk_from_row(row) for row in rows]


def list_whatsapp_people(import_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    statement = (
        select(whatsapp_people)
        .where(whatsapp_people.c.import_id == import_id)
        .order_by(whatsapp_people.c.message_count.desc())
    )
    if user_id is not None:
        statement = statement.where(whatsapp_people.c.user_id == user_id)
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_whatsapp_person_from_row(row) for row in rows]


def list_whatsapp_style_profiles(import_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    statement = (
        select(whatsapp_style_profiles)
        .where(whatsapp_style_profiles.c.import_id == import_id)
        .order_by(whatsapp_style_profiles.c.sender.asc())
    )
    if user_id is not None:
        statement = statement.where(whatsapp_style_profiles.c.user_id == user_id)
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_whatsapp_style_profile_from_row(row) for row in rows]


def delete_context_source(source_id: str, conversation_id: str, user_id: str | None = None) -> bool:
    statement = conversation_context_sources.delete().where(
        conversation_context_sources.c.id == source_id,
        conversation_context_sources.c.conversation_id == conversation_id,
    )
    if user_id is not None:
        statement = statement.where(conversation_context_sources.c.user_id == user_id)

    with ENGINE.begin() as connection:
        _delete_whatsapp_imports_for_context_sources(connection, [source_id], user_id)
        result = connection.execute(statement)
    return result.rowcount > 0


def delete_user_context_source(source_id: str, user_id: str) -> bool:
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(conversation_context_sources).where(
                conversation_context_sources.c.user_id == user_id
            )
        ).mappings().all()
        source_ids = [
            row["id"]
            for row in rows
            if row["id"] == source_id
            or (
                isinstance(row["metadata_json"], dict)
                and row["metadata_json"].get("original_source_id") == source_id
            )
        ]
        if not source_ids:
            return False
        _delete_whatsapp_imports_for_context_sources(connection, source_ids, user_id)
        result = connection.execute(
            conversation_context_sources.delete().where(
                conversation_context_sources.c.id.in_(source_ids)
            )
        )
    return result.rowcount > 0


def _delete_whatsapp_imports_for_context_sources(
    connection: Any,
    source_ids: list[str],
    user_id: str | None = None,
) -> None:
    if not source_ids:
        return
    facts_select = select(profile_facts.c.id).where(
        profile_facts.c.source_kind == "whatsapp_import",
        profile_facts.c.source_id.in_(source_ids),
    )
    if user_id is not None:
        facts_select = facts_select.where(profile_facts.c.user_id == user_id)
    fact_ids = [row[0] for row in connection.execute(facts_select).all()]
    if fact_ids:
        connection.execute(
            data_point_feedback.delete().where(data_point_feedback.c.profile_fact_id.in_(fact_ids))
        )

    facts_statement = profile_facts.delete().where(
        profile_facts.c.source_kind == "whatsapp_import",
        profile_facts.c.source_id.in_(source_ids),
    )
    if user_id is not None:
        facts_statement = facts_statement.where(profile_facts.c.user_id == user_id)
    connection.execute(facts_statement)

    debug_statement = data_point_extraction_debug.delete().where(
        data_point_extraction_debug.c.source_id.in_(source_ids)
    )
    if user_id is not None:
        debug_statement = debug_statement.where(data_point_extraction_debug.c.user_id == user_id)
    connection.execute(debug_statement)

    statement = select(whatsapp_imports.c.id).where(
        whatsapp_imports.c.context_source_id.in_(source_ids)
    )
    if user_id is not None:
        statement = statement.where(whatsapp_imports.c.user_id == user_id)
    import_ids = [row[0] for row in connection.execute(statement).all()]
    if not import_ids:
        return
    import_debug_statement = data_point_extraction_debug.delete().where(
        data_point_extraction_debug.c.import_id.in_(import_ids)
    )
    if user_id is not None:
        import_debug_statement = import_debug_statement.where(
            data_point_extraction_debug.c.user_id == user_id
        )
    connection.execute(import_debug_statement)
    _delete_whatsapp_import_rows(connection, import_ids)
    connection.execute(whatsapp_imports.delete().where(whatsapp_imports.c.id.in_(import_ids)))


def _delete_whatsapp_import_rows(connection: Any, import_ids: list[str]) -> None:
    if not import_ids:
        return
    connection.execute(whatsapp_messages.delete().where(whatsapp_messages.c.import_id.in_(import_ids)))
    connection.execute(whatsapp_chunks.delete().where(whatsapp_chunks.c.import_id.in_(import_ids)))
    connection.execute(whatsapp_people.delete().where(whatsapp_people.c.import_id.in_(import_ids)))
    connection.execute(
        whatsapp_style_profiles.delete().where(whatsapp_style_profiles.c.import_id.in_(import_ids))
    )


def _context_source_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "source_type": row["source_type"],
        "title": row["title"],
        "content": _unprotect_text(row["user_id"], row["content"]),
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _whatsapp_import_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "context_source_id": row["context_source_id"],
        "style_kind": row["style_kind"],
        "title": row["title"],
        "selected_sender": row["selected_sender"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _whatsapp_message_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "import_id": row["import_id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "message_index": row["message_index"],
        "sender": row["sender"],
        "timestamp_text": row["timestamp_text"],
        "content": _unprotect_text(row["user_id"], row["content"]),
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _whatsapp_chunk_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "import_id": row["import_id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "chunk_index": row["chunk_index"],
        "start_message_index": row["start_message_index"],
        "end_message_index": row["end_message_index"],
        "content": _unprotect_text(row["user_id"], row["content"]),
        "terms": row["terms_json"],
        "embedding": row["embedding_json"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _whatsapp_person_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "import_id": row["import_id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "sender": row["sender"],
        "message_count": row["message_count"],
        "role": row["role"],
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _whatsapp_style_profile_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "import_id": row["import_id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "sender": row["sender"],
        "summary": decrypt_json(row["user_id"], row["summary_json"]),
        "sample_messages": decrypt_json(row["user_id"], row["sample_messages_json"]),
        "metadata": row["metadata_json"],
        "created_at": _isoformat_utc(row["created_at"]),
    }


def _protect_messages(user_id: str | None, messages: list[dict[str, Any]]) -> Any:
    return maybe_encrypt_json(user_id, messages)


def _unprotect_messages(user_id: str | None, value: Any) -> list[dict[str, Any]]:
    return decrypt_json(user_id, value)


def _protect_text(user_id: str | None, value: str) -> str:
    protected = maybe_encrypt_text(user_id, value)
    if is_encrypted_blob(protected):
        return json.dumps(protected, separators=(",", ":"))
    return str(protected)


def _unprotect_text(user_id: str | None, value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if is_encrypted_blob(parsed):
                return decrypt_text(user_id, parsed)
    return decrypt_text(user_id, value)


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
