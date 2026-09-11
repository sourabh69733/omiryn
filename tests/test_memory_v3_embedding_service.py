"""Tests configured embedding calls and graceful memory fallback."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from agent.memory_engine.memories.embeddings import (
    embed_memory_query,
    index_agent_memories,
    memory_embedding_target,
)


def test_embedding_target_uses_one_provider_model_setting(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDING_MODEL", "deepinfra:BAAI/bge-m3")

    assert memory_embedding_target() == ("deepinfra", "BAAI/bge-m3")


def test_embedding_target_is_disabled_when_setting_is_absent(monkeypatch) -> None:
    monkeypatch.delenv("MEMORY_EMBEDDING_MODEL", raising=False)

    assert memory_embedding_target() is None


def test_query_embedding_returns_provider_versioned_vector(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDING_MODEL", "deepinfra:BAAI/bge-m3")
    provider = AsyncMock(return_value=[[0.2, 0.8]])

    with patch("agent.memory_engine.memories.embeddings.provider_embeddings", provider):
        result = asyncio.run(embed_memory_query("मुझे शांत लोग पसंद हैं"))

    assert result == {
        "provider": "deepinfra",
        "model": "BAAI/bge-m3",
        "dimensions": 2,
        "values": [0.2, 0.8],
    }
    provider.assert_awaited_once_with(
        provider="deepinfra",
        model="BAAI/bge-m3",
        inputs=["मुझे शांत लोग पसंद हैं"],
        conversation_id=None,
        request_kind="memory_embedding_query",
    )


def test_query_embedding_failure_falls_back_without_breaking_reply(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDING_MODEL", "deepinfra:BAAI/bge-m3")
    provider = AsyncMock(side_effect=RuntimeError("provider unavailable"))

    with patch("agent.memory_engine.memories.embeddings.provider_embeddings", provider):
        assert asyncio.run(embed_memory_query("hello")) is None


def test_memory_indexing_batches_new_memories(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDING_MODEL", "deepinfra:BAAI/bge-m3")
    provider = AsyncMock(return_value=[[1.0, 0.0], [0.0, 1.0]])
    save = patch("agent.memory_engine.memories.embeddings.save_agent_memory_embedding")
    memories = [
        {"id": "m1", "user_id": "u1", "key": "city", "value": "Pune", "purposes": ["profile"]},
        {"id": "m2", "user_id": "u1", "key": "food", "value": "spicy", "purposes": ["matching"]},
    ]

    with patch("agent.memory_engine.memories.embeddings.provider_embeddings", provider), save as save_embedding:
        count = asyncio.run(index_agent_memories(memories, conversation_id="c1"))

    assert count == 2
    assert save_embedding.call_count == 2
    provider.assert_awaited_once()


class ForegroundSemanticRetrievalTest(__import__("unittest").IsolatedAsyncioTestCase):
    async def test_v3_query_embedding_is_passed_into_context_assembly(self) -> None:
        from agent.context_engine.contracts.models import ModelContextPackage
        from agent.runtime.orchestrator import run_agent_turn

        query_embedding = {
            "provider": "deepinfra",
            "model": "BAAI/bge-m3",
            "dimensions": 2,
            "values": [1.0, 0.0],
        }
        with (
            patch.dict("os.environ", {"AGENT_PIPELINE_VERSION": "v3"}),
            patch("agent.runtime.orchestrator.capture_profile_facts_from_user_message"),
            patch(
                "agent.runtime.orchestrator.embed_memory_query",
                new_callable=AsyncMock,
                return_value=query_embedding,
            ) as embed_query,
            patch("agent.runtime.orchestrator.build_model_context_package") as context,
            patch(
                "agent.runtime.orchestrator.generate_agent_reply",
                new_callable=AsyncMock,
                return_value="That sounds important.",
            ),
            patch("agent.runtime.orchestrator.save_agent_context_snapshot"),
            patch("agent.runtime.orchestrator.save_agent_trace") as save_trace,
            patch("agent.runtime.orchestrator.save_agent_trace_step"),
            patch("agent.runtime.orchestrator.finish_agent_trace"),
        ):
            save_trace.return_value = {"id": "trace-semantic-memory"}
            context.return_value = ModelContextPackage(
                system_prompt="system",
                context_sources=[],
                snapshot={"message_index": 1, "summary": {}},
            )
            await run_agent_turn(
                conversation_id="conversation-a",
                messages=[],
                user_text="मुझे शांत लोग पसंद हैं",
                user_id="user-a",
                user_profile=None,
                model="llama-70b",
                agent_mode="know_me",
                agent_tone="auto",
                style_source_id=None,
            )

        embed_query.assert_awaited_once_with(
            "मुझे शांत लोग पसंद हैं", conversation_id="conversation-a"
        )
        assert context.call_args.kwargs["memory_query_embedding"] == query_embedding
