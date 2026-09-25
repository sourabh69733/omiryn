"""Stores versioned vector representations separately from canonical memories."""

from __future__ import annotations

import hashlib
import math
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from .database import ENGINE
from .schema import agent_memories, agent_memory_embeddings, agent_memory_reviews
from .utils import _require_user_id


def embedding_content_hash(content: str) -> str:
    """Fingerprint of the text an embedding was built from; unchanged text needs no new vector."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def save_agent_memory_embedding(
    memory_id: str,
    user_id: str,
    embedding: dict[str, Any],
    *,
    content: str = "",
) -> dict[str, Any]:
    """Upsert one embedding version after verifying memory ownership."""
    owner_id = _require_user_id(user_id, "agent memory embedding")
    provider, model, values = _validated_embedding(embedding)
    content_hash = embedding_content_hash(content)
    with ENGINE.begin() as connection:
        owned = connection.execute(
            select(agent_memories.c.id).where(
                agent_memories.c.id == memory_id,
                agent_memories.c.user_id == owner_id,
            )
        ).first()
        if not owned:
            raise ValueError("agent memory was not found for this user")
        existing = connection.execute(
            select(agent_memory_embeddings).where(
                agent_memory_embeddings.c.memory_id == memory_id,
                agent_memory_embeddings.c.user_id == owner_id,
                agent_memory_embeddings.c.provider == provider,
                agent_memory_embeddings.c.model == model,
            )
        ).mappings().first()
        values_payload = [float(value) for value in values]
        if existing:
            connection.execute(
                agent_memory_embeddings.update()
                .where(agent_memory_embeddings.c.id == existing["id"])
                .values(
                    dimensions=len(values_payload),
                    values_json=values_payload,
                    content_hash=content_hash,
                    updated_at=func.now(),
                )
            )
            embedding_id = existing["id"]
        else:
            embedding_id = str(uuid4())
            connection.execute(
                agent_memory_embeddings.insert().values(
                    id=embedding_id,
                    memory_id=memory_id,
                    user_id=owner_id,
                    provider=provider,
                    model=model,
                    dimensions=len(values_payload),
                    values_json=values_payload,
                    content_hash=content_hash,
                )
            )
        row = connection.execute(
            select(agent_memory_embeddings).where(
                agent_memory_embeddings.c.id == embedding_id
            )
        ).mappings().one()
        return _embedding_from_row(row)


def list_agent_memory_embeddings(
    user_id: str,
    memory_ids: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Return owned embeddings, optionally bounded to candidate memory IDs."""
    owner_id = _require_user_id(user_id, "agent memory embeddings")
    if memory_ids is not None and not memory_ids:
        return []
    query = select(agent_memory_embeddings).where(
        agent_memory_embeddings.c.user_id == owner_id
    )
    if memory_ids is not None:
        query = query.where(agent_memory_embeddings.c.memory_id.in_(memory_ids))
    with ENGINE.begin() as connection:
        rows = connection.execute(query).mappings().all()
    return [_embedding_from_row(row) for row in rows]


def prune_orphan_memory_rows() -> dict[str, int]:
    """Delete vectors and reviews whose memory no longer exists (left by older deletes)."""
    existing = select(agent_memories.c.id)
    deleted: dict[str, int] = {}
    with ENGINE.begin() as connection:
        for table in (agent_memory_embeddings, agent_memory_reviews):
            result = connection.execute(table.delete().where(~table.c.memory_id.in_(existing)))
            deleted[table.name] = int(result.rowcount or 0)
    return deleted


def _validated_embedding(embedding: dict[str, Any]) -> tuple[str, str, list[float]]:
    provider = str(embedding.get("provider") or "").strip().casefold()
    model = str(embedding.get("model") or "").strip()
    values = embedding.get("values")
    dimensions = embedding.get("dimensions")
    if not provider or not model or not isinstance(values, list) or not values:
        raise ValueError("embedding requires provider, model, and values")
    if dimensions != len(values):
        raise ValueError("embedding dimensions do not match its values")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise ValueError("embedding values must be numbers")
    normalized = [float(value) for value in values]
    if any(not math.isfinite(value) for value in normalized):
        raise ValueError("embedding values must be finite")
    return provider, model, normalized


def _embedding_from_row(row) -> dict[str, Any]:
    values = [float(value) for value in (row["values_json"] or [])]
    return {
        "id": row["id"],
        "memory_id": row["memory_id"],
        "user_id": row["user_id"],
        "provider": row["provider"],
        "model": row["model"],
        "dimensions": row["dimensions"],
        "values": values,
        "content_hash": row["content_hash"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


