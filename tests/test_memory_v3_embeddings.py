"""Tests versioned semantic vectors and lexical fallback for V3 memory retrieval."""

from __future__ import annotations

from datetime import UTC, datetime

import storage
from agent.memory_engine.memories.retrieval import retrieve_agent_memories_for_reply


USER_ID = "memory-v3-embedding-user"
CONVERSATION_ID = "memory-v3-embedding-conversation"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def setup_function() -> None:
    storage.reset_db()
    storage.save_conversation(
        {
            "id": CONVERSATION_ID,
            "status": "active",
            "messages": [{"role": "user", "content": "seed"}],
        },
        USER_ID,
    )


def test_semantic_similarity_can_retrieve_memory_across_languages() -> None:
    relevant = _save_memory("weekend.preference", "prefers quiet weekends at home")
    unrelated = _save_memory("food.preference", "likes spicy noodles", importance=1.0)
    storage.save_agent_memory_embedding(
        relevant["id"], USER_ID, _embedding([1.0, 0.0])
    )
    storage.save_agent_memory_embedding(
        unrelated["id"], USER_ID, _embedding([0.0, 1.0])
    )

    selected = retrieve_agent_memories_for_reply(
        USER_ID,
        "मुझे शांत weekend घर पर पसंद है",
        query_embedding=_embedding([1.0, 0.0]),
        now=NOW,
    )

    assert selected[0]["id"] == relevant["id"]


def test_retrieval_ignores_vectors_from_another_embedding_model() -> None:
    lexical_match = _save_memory("relationship.riya", "Riya understands me")
    other = _save_memory("food.preference", "likes pasta")
    storage.save_agent_memory_embedding(
        lexical_match["id"], USER_ID, _embedding([0.0, 1.0], model="old-model")
    )
    storage.save_agent_memory_embedding(
        other["id"], USER_ID, _embedding([1.0, 0.0], model="old-model")
    )

    selected = retrieve_agent_memories_for_reply(
        USER_ID,
        "Riya called me",
        query_embedding=_embedding([1.0, 0.0], model="new-model"),
        now=NOW,
    )

    assert selected[0]["id"] == lexical_match["id"]


def test_memory_embedding_upsert_replaces_same_provider_model_version() -> None:
    memory = _save_memory("home.location", "Pune")

    storage.save_agent_memory_embedding(memory["id"], USER_ID, _embedding([1.0, 0.0]))
    storage.save_agent_memory_embedding(memory["id"], USER_ID, _embedding([0.5, 0.5]))

    embeddings = storage.list_agent_memory_embeddings(USER_ID, [memory["id"]])
    assert len(embeddings) == 1
    assert embeddings[0]["values"] == [0.5, 0.5]


def _embedding(values: list[float], *, model: str = "new-model") -> dict[str, object]:
    return {
        "provider": "test-provider",
        "model": model,
        "dimensions": len(values),
        "values": values,
    }


def _save_memory(key: str, value: object, *, importance: float = 0.8) -> dict[str, object]:
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
            "importance": importance,
            "evidence": [
                {
                    "conversation_id": CONVERSATION_ID,
                    "message_index": 0,
                    "exact_quote": f"Evidence for {key}",
                    "observed_at": NOW.isoformat(),
                }
            ],
        }
    )
