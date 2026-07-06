from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.pool import NullPool

from .schema import DEFAULT_DATABASE_URL, DB_DISABLE_POOL, metadata

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

