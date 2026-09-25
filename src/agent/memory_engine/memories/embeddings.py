"""Builds and persists configurable semantic embeddings for canonical memories."""

from __future__ import annotations

import logging
import os
from typing import Any

from agent.providers.gateway.embeddings import provider_embeddings
from storage.memory_embeddings import (
    embedding_content_hash,
    list_agent_memory_embeddings,
    save_agent_memory_embedding,
)

from .ranking import searchable_memory_text

logger = logging.getLogger(__name__)


# Memories embedded per background run while healing earlier failures; bounds cost per batch.
EMBEDDING_REFRESH_LIMIT = 50

# Multilingual, so Hindi and Hinglish memories share a vector space with English ones.
DEFAULT_MEMORY_EMBEDDING_MODEL = "deepinfra:BAAI/bge-m3"
_DISABLED_VALUES = {"off", "none", "disabled"}


def memory_embedding_target() -> tuple[str, str] | None:
    """Parse the single `provider:model` setting used to version vector space.

    Unset uses the default model; `off` disables semantic recall (keyword-only).
    """
    configured = os.getenv("MEMORY_EMBEDDING_MODEL", "").strip() or DEFAULT_MEMORY_EMBEDDING_MODEL
    if configured.casefold() in _DISABLED_VALUES:
        return None
    provider, separator, model = configured.partition(":")
    if not separator or not provider.strip() or not model.strip():
        raise ValueError("MEMORY_EMBEDDING_MODEL must use provider:model")
    return provider.strip().casefold(), model.strip()


def query_embedding_timeout_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("MEMORY_EMBEDDING_QUERY_TIMEOUT_SECONDS", "8")))
    except ValueError:
        return 8.0


# A message this short usually leans on the previous turns ("what about her?").
_SHORT_QUERY_TOKEN_LIMIT = 8
_QUERY_HISTORY_MESSAGES = 2
_QUERY_HISTORY_CHARS = 300


def memory_query_text(user_text: str, history: list[dict[str, Any]] | None = None) -> str:
    """Add the last turns to a short message so semantic recall can resolve follow-ups."""
    if not history or len(user_text.split()) > _SHORT_QUERY_TOKEN_LIMIT:
        return user_text
    recent = [
        str(message.get("content") or "").strip()[:_QUERY_HISTORY_CHARS]
        for message in history[-_QUERY_HISTORY_MESSAGES:]
        if message.get("role") in {"user", "assistant"}
    ]
    return "\n".join([*(text for text in recent if text), user_text])


async def embed_memory_query(
    text: str,
    *,
    conversation_id: str | None = None,
) -> dict[str, Any] | None:
    """Embed one retrieval query, returning None when semantic search is unavailable."""
    try:
        target = memory_embedding_target()
        if target is None or not text.strip():
            return None
        provider, model = target
        vectors = await provider_embeddings(
            provider=provider,
            model=model,
            inputs=[text.strip()],
            conversation_id=conversation_id,
            request_kind="memory_embedding_query",
            # A reply waits on this call; fall back to keyword recall rather than stall.
            timeout_seconds=query_embedding_timeout_seconds(),
        )
        return _embedding(provider, model, vectors[0])
    except Exception as error:
        logger.warning("agent.memory_embedding.query_failed error=%s", type(error).__name__)
        return None


async def index_agent_memories(
    memories: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    conversation_id: str | None = None,
) -> int:
    """Embed a changed memory batch once; memory writes remain valid on failure."""
    try:
        target = memory_embedding_target()
        candidates = [memory for memory in memories if memory.get("id") and memory.get("user_id")]
        if target is None or not candidates:
            return 0
        provider, model = target
        candidates = memories_needing_embeddings(candidates, provider, model)
        if not candidates:
            return 0
        texts = [searchable_memory_text(memory) for memory in candidates]
        vectors = await provider_embeddings(
            provider=provider,
            model=model,
            inputs=texts,
            conversation_id=conversation_id,
            user_id=_single_owner(candidates),
            request_kind="memory_embedding_index",
        )
        if len(vectors) != len(candidates):
            raise ValueError("embedding result count does not match memory count")
        for memory, content, values in zip(candidates, texts, vectors, strict=True):
            save_agent_memory_embedding(
                str(memory["id"]),
                str(memory["user_id"]),
                _embedding(provider, model, values),
                content=content,
            )
        return len(candidates)
    except Exception as error:
        logger.warning("agent.memory_embedding.index_failed error=%s", type(error).__name__)
        return 0


def memories_needing_embeddings(
    memories: list[dict[str, Any]], provider: str, model: str
) -> list[dict[str, Any]]:
    """Memories with no vector for this model, or whose text changed since it was built."""
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for memory in memories:
        by_owner.setdefault(str(memory["user_id"]), []).append(memory)
    needed: list[dict[str, Any]] = []
    for owner, owned in by_owner.items():
        hashes = {
            str(item["memory_id"]): item["content_hash"]
            for item in list_agent_memory_embeddings(owner, [str(m["id"]) for m in owned])
            if item.get("provider") == provider and item.get("model") == model
        }
        needed.extend(
            memory
            for memory in owned
            if hashes.get(str(memory["id"]))
            != embedding_content_hash(searchable_memory_text(memory))
        )
    return needed


async def refresh_user_memory_embeddings(
    user_id: str,
    *,
    conversation_id: str | None = None,
    limit: int = EMBEDDING_REFRESH_LIMIT,
) -> int:
    """Embed active memories an earlier run failed to embed, a few per call; never raises."""
    try:
        target = memory_embedding_target()
        if target is None:
            return 0
        # Local import keeps storage initialization independent of this module.
        from storage.memories import list_agent_memories

        active = [m for m in list_agent_memories(user_id) if m.get("status") == "active"]
        pending = memories_needing_embeddings(active, *target)[:limit]
        return await index_agent_memories(pending, conversation_id=conversation_id)
    except Exception as error:
        logger.warning("agent.memory_embedding.refresh_failed error=%s", type(error).__name__)
        return 0


def _single_owner(memories: list[dict[str, Any]]) -> str | None:
    """Attribute usage to the owner when a batch has exactly one (backfills have no chat)."""
    owners = {str(memory["user_id"]) for memory in memories}
    return owners.pop() if len(owners) == 1 else None


def _embedding(provider: str, model: str, values: list[float]) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "dimensions": len(values),
        "values": [float(value) for value in values],
    }


__all__ = [
    "DEFAULT_MEMORY_EMBEDDING_MODEL",
    "embed_memory_query",
    "index_agent_memories",
    "memory_embedding_target",
    "memory_query_text",
    "memories_needing_embeddings",
    "refresh_user_memory_embeddings",
]
