"""Builds the vectors meaning search reads: one per chunk of consecutive messages in a chat.

Chunks are fixed runs of CHUNK_SIZE messages, so a long chat costs few vectors and a new message
only changes the last chunk. Each chunk keeps a hash of its text; an unchanged chunk is never
embedded again. Runs in the background after memory runs and uploads; a failure only leaves search
on words for a while.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.memory_engine.memories.embeddings import memory_embedding_target
from agent.providers.gateway.embeddings import provider_embeddings
from storage import get_conversation, list_conversations
from storage.chat_embeddings import chunk_hashes, save_chunk_embedding
from storage.memory_embeddings import embedding_content_hash

logger = logging.getLogger(__name__)

# Small chunks keep one subject per vector; a chunk mixing subjects matches none of them well.
CHUNK_SIZE = 4
CHUNK_CHARS = 2000
BATCH = 32


def embedding_target() -> tuple[str, str] | None:
    """The same multilingual model as memories (MEMORY_EMBEDDING_MODEL), or None when off."""
    try:
        return memory_embedding_target()
    except ValueError:
        return None


def chat_chunks(messages: list[dict[str, Any]]) -> list[tuple[int, int, int, str]]:
    """(chunk_index, first message, last message, text) for every chunk with something in it."""
    partner = next((m.get("speaker") for m in messages if m.get("role") == "other" and m.get("speaker")), None)
    chunks = []
    for chunk_index, start in enumerate(range(0, len(messages), CHUNK_SIZE)):
        end = min(start + CHUNK_SIZE, len(messages)) - 1
        lines = []
        for message in messages[start : end + 1]:
            text = " ".join(str(message.get("content") or "").split())
            if not text:
                continue
            role = message.get("role")
            who = "User" if role == "user" else "Omi" if role == "assistant" else (message.get("speaker") or partner or "Them")
            lines.append(f"{who}: {text}")
        if lines:
            chunks.append((chunk_index, start, end, "\n".join(lines)[:CHUNK_CHARS]))
    return chunks


async def index_chat(user_id: str, conversation_id: str) -> int:
    """Embed the chunks of one chat that are new or changed; returns how many."""
    target = embedding_target()
    conversation = get_conversation(conversation_id, user_id) if target else None
    if target is None or conversation is None or conversation.get("temporary"):
        return 0
    provider, model = target
    stored = chunk_hashes(user_id, conversation_id, provider, model)
    pending = [
        (chunk, embedding_content_hash(chunk[3]))
        for chunk in chat_chunks(list(conversation.get("messages") or []))
    ]
    pending = [(chunk, digest) for chunk, digest in pending if stored.get(chunk[0]) != digest]
    done = 0
    try:
        for offset in range(0, len(pending), BATCH):
            batch = pending[offset : offset + BATCH]
            vectors = await provider_embeddings(
                provider=provider,
                model=model,
                inputs=[chunk[3] for chunk, _ in batch],
                conversation_id=conversation_id,
                user_id=user_id,
                request_kind="chat_embedding_index",
            )
            for ((chunk_index, start, end, _), digest), values in zip(batch, vectors, strict=True):
                save_chunk_embedding(user_id, conversation_id, chunk_index, start, end, provider, model, list(values), digest)
                done += 1
    except Exception as error:
        logger.warning("agent.chat_index.failed conversation_id=%s error_type=%s", conversation_id, type(error).__name__)
    return done


async def index_user_chats(user_id: str) -> int:
    """Every stored chat of one user; for backfills."""
    total = 0
    for summary in list_conversations(user_id):
        if not summary.get("temporary"):
            total += await index_chat(user_id, summary["id"])
    return total


__all__ = ["CHUNK_SIZE", "chat_chunks", "embedding_target", "index_chat", "index_user_chats"]
