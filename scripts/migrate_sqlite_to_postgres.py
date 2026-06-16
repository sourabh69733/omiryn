#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_URL = "sqlite:///./data/omiryn.db"
TABLE_ORDER = (
    "draft_profiles",
    "agent_conversations",
    "agent_usage_events",
    "conversation_context_sources",
)


def main() -> None:
    if load_dotenv:
        load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Migrate Omiryn runtime data from local SQLite to configured Postgres."
    )
    parser.add_argument(
        "--sqlite-url",
        default=DEFAULT_SQLITE_URL,
        help=f"Source SQLite URL. Defaults to {DEFAULT_SQLITE_URL}.",
    )
    parser.add_argument(
        "--target-url",
        default=os.getenv("DATABASE_URL"),
        help="Target Postgres URL. Defaults to DATABASE_URL from .env.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows without writing to the target database.",
    )
    args = parser.parse_args()

    if not args.target_url:
        raise SystemExit("DATABASE_URL is not set. Add it to .env or pass --target-url.")

    source_url = _resolve_sqlite_url(args.sqlite_url)
    target_url = _normalize_database_url(args.target_url)
    if target_url.startswith("sqlite"):
        raise SystemExit("Target URL is SQLite. Set DATABASE_URL to your cloud Postgres URL.")

    _configure_storage_environment(target_url)
    from storage import metadata

    source_engine = create_engine(source_url, connect_args={"check_same_thread": False})
    print(f"Source: {_safe_url(source_url)}")
    print(f"Target: {_safe_url(target_url)}")

    target_engine = None if args.dry_run else create_engine(target_url)
    if target_engine is not None:
        metadata.create_all(target_engine)

    total = 0
    for table_name in TABLE_ORDER:
        table = metadata.tables[table_name]
        rows = _read_rows(source_engine, table)
        print(f"{table_name}: {len(rows)} row(s)")
        if target_engine is not None:
            _upsert_rows(target_engine, table, rows)
        total += len(rows)

    action = "Checked" if args.dry_run else "Migrated"
    print(f"{action} {total} row(s).")


def _configure_storage_environment(target_url: str) -> None:
    os.environ["DATABASE_URL"] = target_url
    pythonpath = os.environ.get("PYTHONPATH")
    src_path = str(PROJECT_ROOT / "src")
    if pythonpath:
        os.environ["PYTHONPATH"] = f"{src_path}{os.pathsep}{pythonpath}"
    else:
        os.environ["PYTHONPATH"] = src_path

    import sys

    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def _resolve_sqlite_url(url: str) -> str:
    if not url.startswith("sqlite:///"):
        return url

    raw_path = url.removeprefix("sqlite:///")
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise SystemExit(f"Source SQLite database does not exist: {path}")
    return f"sqlite:///{path}"


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _read_rows(engine: Engine, table: Any) -> list[dict[str, Any]]:
    with engine.begin() as connection:
        rows = connection.execute(select(table)).mappings().all()

    return [_coerce_row(dict(row), table) for row in rows]


def _coerce_row(row: dict[str, Any], table: Any) -> dict[str, Any]:
    for column in table.columns:
        value = row.get(column.name)
        if value is None:
            continue

        if column.name.endswith("_json") or column.name in {"messages_json", "submission_json"}:
            row[column.name] = _coerce_json(value)
        elif column.name in {"created_at", "updated_at"}:
            row[column.name] = _coerce_datetime(value)
        elif column.name == "success":
            row[column.name] = bool(value)

    return row


def _coerce_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _coerce_datetime(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return value


def _upsert_rows(engine: Engine, table: Any, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    primary_key = list(table.primary_key.columns)[0]
    with engine.begin() as connection:
        for row in rows:
            existing = connection.execute(
                select(primary_key).where(primary_key == row[primary_key.name])
            ).first()
            if existing:
                update_values = {
                    key: value
                    for key, value in row.items()
                    if key != primary_key.name and key in table.columns
                }
                connection.execute(
                    table.update()
                    .where(primary_key == row[primary_key.name])
                    .values(**update_values)
                )
            else:
                connection.execute(table.insert().values(**row))


def _safe_url(url: str) -> str:
    if "://" not in url:
        return url

    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return f"{scheme}://{rest}"

    _, host = rest.rsplit("@", 1)
    return f"{scheme}://***:***@{host}"


if __name__ == "__main__":
    main()
