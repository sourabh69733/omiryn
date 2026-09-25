"""Embedding upkeep: skip unchanged text, heal failed embeddings, remove orphan rows."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import storage
from agent.memory_engine.memories.embeddings import (
    index_agent_memories,
    refresh_user_memory_embeddings,
)
from storage.database import ENGINE
from storage.schema import agent_memory_embeddings

USER_ID = "embedding-upkeep-user"
CONVERSATION_ID = "embedding-upkeep-conversation"
OTHER_CONVERSATION_ID = "embedding-upkeep-other"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
ENV = {"MEMORY_EMBEDDING_MODEL": "deepinfra:test-model"}


def setup_function() -> None:
    storage.reset_db()
    for conversation_id in (CONVERSATION_ID, OTHER_CONVERSATION_ID):
        storage.save_conversation(
            {"id": conversation_id, "status": "active", "messages": [{"role": "user", "content": "seed"}]},
            USER_ID,
        )


def _save_memory(key: str, value: str, conversation_id: str = CONVERSATION_ID) -> dict:
    return storage.create_agent_memory(
        {
            "user_id": USER_ID,
            "kind": "semantic",
            "purposes": ["profile"],
            "key": key,
            "value": value,
            "allowed_uses": ["reply_context"],
            "status": "active",
            "sensitivity": "standard",
            "confidence": 0.9,
            "importance": 0.8,
            "evidence": [
                {
                    "conversation_id": conversation_id,
                    "message_index": 0,
                    "exact_quote": f"Evidence for {key}",
                    "observed_at": NOW.isoformat(),
                }
            ],
        }
    )


def _fake_embeddings() -> AsyncMock:
    async def embed(**kwargs):
        return [[1.0, 0.0] for _ in kwargs["inputs"]]

    return AsyncMock(side_effect=embed)


def _embedded_texts(provider: AsyncMock) -> list[str]:
    return [text for call in provider.await_args_list for text in call.kwargs["inputs"]]


def test_unchanged_memory_is_not_embedded_again() -> None:
    memory = _save_memory("home.city", "Pune")
    provider = _fake_embeddings()
    with patch.dict(os.environ, ENV), patch(
        "agent.memory_engine.memories.embeddings.provider_embeddings", new=provider
    ):
        assert asyncio.run(index_agent_memories([memory])) == 1
        assert asyncio.run(index_agent_memories([memory])) == 0
        changed = {**memory, "statement": "Lives in Pune."}
        assert asyncio.run(index_agent_memories([changed])) == 1
    assert provider.await_count == 2


def test_refresh_embeds_only_memories_missing_a_vector() -> None:
    done = _save_memory("home.city", "Pune")
    failed = _save_memory("pets.dog", "Bruno")
    provider = _fake_embeddings()
    with patch.dict(os.environ, ENV), patch(
        "agent.memory_engine.memories.embeddings.provider_embeddings", new=provider
    ):
        asyncio.run(index_agent_memories([done]))
        provider.reset_mock()
        assert asyncio.run(refresh_user_memory_embeddings(USER_ID)) == 1
        assert asyncio.run(refresh_user_memory_embeddings(USER_ID)) == 0
    [embedded] = _embedded_texts(provider)
    assert "Bruno" in embedded
    assert {e["memory_id"] for e in storage.list_agent_memory_embeddings(USER_ID)} == {
        done["id"],
        failed["id"],
    }


def test_refresh_never_raises() -> None:
    _save_memory("home.city", "Pune")
    with patch.dict(os.environ, ENV), patch(
        "agent.memory_engine.memories.embeddings.provider_embeddings",
        new=AsyncMock(side_effect=TimeoutError("down")),
    ):
        assert asyncio.run(refresh_user_memory_embeddings(USER_ID)) == 0


def test_deleting_a_conversation_removes_vectors_and_reviews_of_its_memories() -> None:
    gone = _save_memory("home.city", "Pune")
    kept = _save_memory("pets.dog", "Bruno", conversation_id=OTHER_CONVERSATION_ID)
    for memory in (gone, kept):
        storage.save_agent_memory_embedding(
            memory["id"], USER_ID, {"provider": "p", "model": "m", "dimensions": 1, "values": [1.0]}
        )
        storage.review_agent_memory(memory["id"], USER_ID, "agree")

    storage.delete_conversation(CONVERSATION_ID, USER_ID)

    assert {e["memory_id"] for e in storage.list_agent_memory_embeddings(USER_ID)} == {kept["id"]}
    assert storage.list_agent_memory_reviews(USER_ID, gone["id"]) == []
    assert len(storage.list_agent_memory_reviews(USER_ID, kept["id"])) == 1


def test_prune_removes_rows_left_by_older_deletes() -> None:
    memory = _save_memory("home.city", "Pune")
    storage.save_agent_memory_embedding(
        memory["id"], USER_ID, {"provider": "p", "model": "m", "dimensions": 1, "values": [1.0]}
    )
    with ENGINE.begin() as connection:
        connection.execute(
            agent_memory_embeddings.insert().values(
                id="orphan", memory_id="deleted-memory", user_id=USER_ID, provider="p", model="m",
                dimensions=1, values_json=[1.0], content_hash="x",
            )
        )

    assert storage.prune_orphan_memory_rows()["agent_memory_embeddings"] == 1
    assert [e["memory_id"] for e in storage.list_agent_memory_embeddings(USER_ID)] == [memory["id"]]
