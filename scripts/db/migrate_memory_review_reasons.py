"""Backfill canonical memory-review reason arrays from the legacy single reason."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import Engine

DEFAULT_DATABASE_URL = "sqlite:///./data/omiryn.db"
TABLE_NAME = "agent_memory_reviews"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - dotenv is optional for the script.
    load_dotenv = None

if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")


def migrate_memory_review_reasons(engine: Engine, *, apply: bool) -> dict[str, int]:
    """Preview or apply an idempotent legacy `reason` to `reasons` backfill."""
    columns = _column_names(engine)
    if not columns:
        raise RuntimeError(f"{TABLE_NAME} table does not exist")
    if "reason" not in columns:
        return _empty_result()

    if apply and "reasons" not in columns:
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {TABLE_NAME} ADD COLUMN reasons JSON"))
        columns = _column_names(engine)

    rows = _review_rows(engine, has_reasons="reasons" in columns)
    pending: list[tuple[str, list[str]]] = []
    legacy_count = 0
    empty_count = 0
    for row in rows:
        if _has_initialized_reasons(row["reasons"]):
            continue
        reason = _normalize_reason(row["reason"])
        reasons = [reason] if reason else []
        pending.append((str(row["id"]), reasons))
        if reason:
            legacy_count += 1
        else:
            empty_count += 1

    if apply and pending:
        reviews = Table(TABLE_NAME, MetaData(), autoload_with=engine)
        with engine.begin() as connection:
            for review_id, reasons in pending:
                connection.execute(
                    reviews.update().where(reviews.c.id == review_id).values(reasons=reasons)
                )

    return {
        "rows_scanned": len(rows),
        "legacy_reasons_to_migrate": legacy_count,
        "empty_arrays_to_initialize": empty_count,
        "rows_updated": len(pending) if apply else 0,
    }


def _column_names(engine: Engine) -> set[str]:
    inspector = inspect(engine)
    if TABLE_NAME not in inspector.get_table_names():
        return set()
    return {str(column["name"]) for column in inspector.get_columns(TABLE_NAME)}


def _review_rows(engine: Engine, *, has_reasons: bool) -> list[dict[str, object]]:
    reasons_expression = "reasons" if has_reasons else "NULL AS reasons"
    with engine.begin() as connection:
        rows = connection.execute(
            text(f"SELECT id, reason, {reasons_expression} FROM {TABLE_NAME}")
        ).mappings().all()
    return [dict(row) for row in rows]


def _has_initialized_reasons(value: object) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return bool(value.strip())
    return isinstance(value, list)


def _normalize_reason(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "_")[:80]


def _empty_result() -> dict[str, int]:
    return {
        "rows_scanned": 0,
        "legacy_reasons_to_migrate": 0,
        "empty_arrays_to_initialize": 0,
        "rows_updated": 0,
    }


def _database_url(explicit_url: str | None) -> str:
    url = explicit_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill V3 memory-review reasons without deleting the legacy reason column."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Write the migration.")
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL for this run.",
    )
    args = parser.parse_args()

    engine = create_engine(_database_url(args.database_url), pool_pre_ping=True)
    try:
        result = migrate_memory_review_reasons(engine, apply=args.apply)
    finally:
        engine.dispose()

    mode_name = "APPLY" if args.apply else "DRY RUN"
    print(f"Memory review reasons migration ({mode_name})")
    print(f"Rows scanned: {result['rows_scanned']}")
    print(f"Legacy reasons to migrate: {result['legacy_reasons_to_migrate']}")
    print(f"Empty arrays to initialize: {result['empty_arrays_to_initialize']}")
    print(f"Rows updated: {result['rows_updated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
