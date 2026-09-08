from sqlalchemy import JSON, Column, MetaData, String, Table, create_engine, inspect, select

from scripts.db.migrate_memory_review_reasons import migrate_memory_review_reasons


def _legacy_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    metadata = MetaData()
    reviews = Table(
        "agent_memory_reviews",
        metadata,
        Column("id", String, primary_key=True),
        Column("reason", String, nullable=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            reviews.insert(),
            [
                {"id": "legacy", "reason": "outdated"},
                {"id": "empty", "reason": None},
            ],
        )
    return engine


def test_dry_run_reports_backfill_without_changing_legacy_database(tmp_path) -> None:
    engine = _legacy_engine(tmp_path)

    result = migrate_memory_review_reasons(engine, apply=False)

    assert result == {
        "rows_scanned": 2,
        "legacy_reasons_to_migrate": 1,
        "empty_arrays_to_initialize": 1,
        "rows_updated": 0,
    }
    assert "reasons" not in {column["name"] for column in inspect(engine).get_columns("agent_memory_reviews")}


def test_apply_backfills_reason_and_is_safe_to_rerun(tmp_path) -> None:
    engine = _legacy_engine(tmp_path)

    first = migrate_memory_review_reasons(engine, apply=True)
    second = migrate_memory_review_reasons(engine, apply=True)

    reviews = Table("agent_memory_reviews", MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        rows = {row.id: row.reasons for row in connection.execute(select(reviews)).all()}
    assert rows == {"legacy": ["outdated"], "empty": []}
    assert first["rows_updated"] == 2
    assert second["rows_updated"] == 0


def test_apply_preserves_existing_reason_arrays(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'modern.db'}")
    metadata = MetaData()
    reviews = Table(
        "agent_memory_reviews",
        metadata,
        Column("id", String, primary_key=True),
        Column("reason", String, nullable=True),
        Column("reasons", JSON, nullable=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            reviews.insert().values(
                id="modern",
                reason="outdated",
                reasons=["missing_context"],
            )
        )

    result = migrate_memory_review_reasons(engine, apply=True)

    with engine.begin() as connection:
        row = connection.execute(select(reviews)).one()
    assert row.reasons == ["missing_context"]
    assert result["rows_updated"] == 0
