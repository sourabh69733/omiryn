from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from security.encryption import decrypt_json, maybe_encrypt_json

from .database import ENGINE
from .schema import (
    conversation_context_sources,
    data_point_extraction_debug,
    data_point_feedback,
    profile_facts,
    whatsapp_chunks,
    whatsapp_imports,
    whatsapp_messages,
    whatsapp_people,
    whatsapp_style_profiles,
)
from .utils import (
    _conversation_user_id,
    _isoformat_utc,
    _protect_text,
    _require_user_id,
    _unprotect_text,
)

def save_context_source(source: dict[str, Any]) -> dict[str, Any]:
    source_user_id = _require_user_id(
        source.get("user_id") or _conversation_user_id(source["conversation_id"]),
        "context source",
    )
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
    owner_id = _require_user_id(user_id, "context source list")
    statement = (
        select(conversation_context_sources)
        .where(conversation_context_sources.c.conversation_id == conversation_id)
        .where(conversation_context_sources.c.user_id == owner_id)
        .order_by(conversation_context_sources.c.created_at.desc())
    )

    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_context_source_from_row(row) for row in rows]


def save_whatsapp_import_bundle(
    bundle: dict[str, Any],
    user_id: str | None = None,
) -> dict[str, Any]:
    import_id = bundle.get("id") or str(uuid4())
    import_user_id = _require_user_id(
        user_id or bundle.get("user_id") or _conversation_user_id(bundle.get("conversation_id")),
        "WhatsApp import",
    )
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
                    whatsapp_imports.c.context_source_id == import_payload["context_source_id"],
                    whatsapp_imports.c.user_id == import_user_id,
                )
            ).all()
        ]
        _delete_whatsapp_import_rows(connection, existing_import_ids)
        if existing_import_ids:
            connection.execute(
                whatsapp_imports.delete().where(
                    whatsapp_imports.c.id.in_(existing_import_ids),
                    whatsapp_imports.c.user_id == import_user_id,
                )
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
    owner_id = _require_user_id(user_id, "WhatsApp import list")
    statement = (
        select(whatsapp_imports)
        .where(whatsapp_imports.c.user_id == owner_id)
        .order_by(whatsapp_imports.c.created_at.desc())
    )
    if conversation_id:
        statement = statement.where(whatsapp_imports.c.conversation_id == conversation_id)
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_whatsapp_import_from_row(row) for row in rows]


def list_whatsapp_messages(import_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    owner_id = _require_user_id(user_id, "WhatsApp message list")
    statement = (
        select(whatsapp_messages)
        .where(whatsapp_messages.c.import_id == import_id)
        .where(whatsapp_messages.c.user_id == owner_id)
        .order_by(whatsapp_messages.c.message_index.asc())
    )
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_whatsapp_message_from_row(row) for row in rows]


def list_whatsapp_chunks(import_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    owner_id = _require_user_id(user_id, "WhatsApp chunk list")
    statement = (
        select(whatsapp_chunks)
        .where(whatsapp_chunks.c.import_id == import_id)
        .where(whatsapp_chunks.c.user_id == owner_id)
        .order_by(whatsapp_chunks.c.chunk_index.asc())
    )
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_whatsapp_chunk_from_row(row) for row in rows]


def list_whatsapp_people(import_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    owner_id = _require_user_id(user_id, "WhatsApp people list")
    statement = (
        select(whatsapp_people)
        .where(whatsapp_people.c.import_id == import_id)
        .where(whatsapp_people.c.user_id == owner_id)
        .order_by(whatsapp_people.c.message_count.desc())
    )
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_whatsapp_person_from_row(row) for row in rows]


def list_whatsapp_style_profiles(import_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    owner_id = _require_user_id(user_id, "WhatsApp style profile list")
    statement = (
        select(whatsapp_style_profiles)
        .where(whatsapp_style_profiles.c.import_id == import_id)
        .where(whatsapp_style_profiles.c.user_id == owner_id)
        .order_by(whatsapp_style_profiles.c.sender.asc())
    )
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [_whatsapp_style_profile_from_row(row) for row in rows]


def delete_context_source(source_id: str, conversation_id: str, user_id: str | None = None) -> bool:
    owner_id = _require_user_id(user_id, "context source")
    statement = conversation_context_sources.delete().where(
        conversation_context_sources.c.id == source_id,
        conversation_context_sources.c.conversation_id == conversation_id,
        conversation_context_sources.c.user_id == owner_id,
    )

    with ENGINE.begin() as connection:
        _delete_whatsapp_imports_for_context_sources(connection, [source_id], owner_id)
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
