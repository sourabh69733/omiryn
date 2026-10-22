"""Vectors for chunks of stored chat messages, for meaning search (see agent.memory_engine.search)."""

from __future__ import annotations

import array
import base64
from typing import Any

from sqlalchemy import delete, select

from .database import ENGINE
from .schema import chat_chunk_embeddings
from .utils import _require_user_id


def encode_vector(values: list[float]) -> str:
    return base64.b64encode(array.array("f", values).tobytes()).decode("ascii")


def decode_vector(text: str) -> list[float]:
    vector = array.array("f")
    vector.frombytes(base64.b64decode(text))
    return vector.tolist()


def chunk_hashes(user_id: str, conversation_id: str, provider: str, model: str) -> dict[int, str]:
    """chunk_index -> content_hash of what is stored for this chat and model."""
    owner_id = _require_user_id(user_id, "chat embedding")
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(chat_chunk_embeddings.c.chunk_index, chat_chunk_embeddings.c.content_hash).where(
                chat_chunk_embeddings.c.user_id == owner_id,
                chat_chunk_embeddings.c.conversation_id == conversation_id,
                chat_chunk_embeddings.c.provider == provider,
                chat_chunk_embeddings.c.model == model,
            )
        ).all()
    return {row[0]: row[1] for row in rows}


def save_chunk_embedding(
    user_id: str,
    conversation_id: str,
    chunk_index: int,
    start_index: int,
    end_index: int,
    provider: str,
    model: str,
    values: list[float],
    content_hash: str,
) -> None:
    owner_id = _require_user_id(user_id, "chat embedding")
    row_id = f"{conversation_id}:{chunk_index}:{provider}:{model}"
    with ENGINE.begin() as connection:
        connection.execute(delete(chat_chunk_embeddings).where(chat_chunk_embeddings.c.id == row_id, chat_chunk_embeddings.c.user_id == owner_id))
        connection.execute(
            chat_chunk_embeddings.insert().values(
                id=row_id,
                user_id=owner_id,
                conversation_id=conversation_id,
                chunk_index=chunk_index,
                start_index=start_index,
                end_index=end_index,
                provider=provider,
                model=model,
                vector=encode_vector(values),
                content_hash=content_hash,
            )
        )


def list_chunk_embeddings(user_id: str, provider: str, model: str, conversation_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Every chunk vector of this user for one model, optionally only some chats."""
    owner_id = _require_user_id(user_id, "chat embedding")
    statement = select(chat_chunk_embeddings).where(
        chat_chunk_embeddings.c.user_id == owner_id,
        chat_chunk_embeddings.c.provider == provider,
        chat_chunk_embeddings.c.model == model,
    )
    if conversation_ids is not None:
        statement = statement.where(chat_chunk_embeddings.c.conversation_id.in_(conversation_ids))
    with ENGINE.begin() as connection:
        rows = connection.execute(statement).mappings().all()
    return [
        {
            "conversation_id": row["conversation_id"],
            "chunk_index": row["chunk_index"],
            "start_index": row["start_index"],
            "end_index": row["end_index"],
            "vector": decode_vector(row["vector"]),
        }
        for row in rows
    ]


def delete_chat_embeddings(user_id: str, conversation_id: str) -> None:
    owner_id = _require_user_id(user_id, "chat embedding")
    with ENGINE.begin() as connection:
        connection.execute(
            delete(chat_chunk_embeddings).where(chat_chunk_embeddings.c.user_id == owner_id, chat_chunk_embeddings.c.conversation_id == conversation_id)
        )


__all__ = [
    "chunk_hashes",
    "decode_vector",
    "delete_chat_embeddings",
    "encode_vector",
    "list_chunk_embeddings",
    "save_chunk_embedding",
]
