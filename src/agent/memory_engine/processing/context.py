"""Builds bounded, cross-batch context without making storage or LLM calls."""

from __future__ import annotations

import hashlib

from .models import (
    MemoryBatch,
    MemoryHandoff,
    MemoryMessage,
    MemoryProcessingState,
    MemoryScope,
)

DEFAULT_CONTEXT_OVERLAP = 12
DEFAULT_MAX_MEANINGFUL_USER_MESSAGES = 7
_LOW_INFORMATION_QUALITIES = {"low_information", "simple_acknowledgement"}


def build_memory_batch(
    *,
    conversation_id: str,
    user_id: str,
    messages: list[dict[str, object]],
    state: MemoryProcessingState | None = None,
    context_overlap: int = DEFAULT_CONTEXT_OVERLAP,
    max_meaningful_user_messages: int = DEFAULT_MAX_MEANINGFUL_USER_MESSAGES,
) -> MemoryBatch | None:
    """Select new messages and mark older overlap as context-only.

    The cursor controls which messages are new. The meaningful-user limit bounds
    work, while assistant and low-information messages inside that range remain
    available for interpretation. Only new user messages may become evidence.
    """
    if context_overlap < 0:
        raise ValueError("context_overlap cannot be negative")
    if max_meaningful_user_messages <= 0:
        raise ValueError("max_meaningful_user_messages must be positive")
    if state and (
        state.conversation_id != conversation_id or state.user_id != user_id
    ):
        raise ValueError("memory processing state does not belong to this conversation")

    cursor = state.processed_through_message_index if state else -1
    indexed = [_normalized_message(message, index) for index, message in enumerate(messages)]
    pending = [message for message in indexed if int(message["message_index"]) > cursor]
    if not pending:
        return None

    end_index = _batch_end_index(pending, max_meaningful_user_messages)
    new_rows = [message for message in pending if int(message["message_index"]) <= end_index]
    start_index = int(new_rows[0]["message_index"])
    prior_rows = [
        message for message in indexed if int(message["message_index"]) < start_index
    ]
    context_rows = prior_rows[-context_overlap:] if context_overlap else []

    batch_messages = tuple(
        [_memory_message(message, scope="context") for message in context_rows]
        + [_memory_message(message, scope="new") for message in new_rows]
    )
    meaningful_count = sum(_is_meaningful_user_message(message) for message in new_rows)
    return MemoryBatch(
        batch_key=_batch_key(conversation_id, new_rows),
        conversation_id=conversation_id,
        user_id=user_id,
        messages=batch_messages,
        new_start_message_index=start_index,
        new_end_message_index=end_index,
        meaningful_user_message_count=meaningful_count,
        previous_handoff=state.handoff if state else MemoryHandoff(),
    )


def _batch_end_index(
    pending: list[dict[str, object]],
    max_meaningful_user_messages: int,
) -> int:
    meaningful_seen = 0
    threshold_index: int | None = None
    for position, message in enumerate(pending):
        if _is_meaningful_user_message(message):
            meaningful_seen += 1
            if meaningful_seen == max_meaningful_user_messages:
                threshold_index = int(message["message_index"])
                continue
            if threshold_index is not None:
                return int(pending[position - 1]["message_index"])
    if threshold_index is not None:
        # Include the assistant response and lightweight continuation following
        # the threshold turn, stopping before the next meaningful user message.
        return int(pending[-1]["message_index"])
    return int(pending[-1]["message_index"])


def _normalized_message(message: dict[str, object], index: int) -> dict[str, object]:
    return {
        **message,
        # Conversation position is canonical. Caller-provided indexes may belong
        # to a filtered window and must not redefine evidence identity.
        "message_index": index,
        "role": str(message.get("role") or ""),
        "content": str(message.get("content") or ""),
    }


def _memory_message(message: dict[str, object], *, scope: MemoryScope) -> MemoryMessage:
    role = str(message["role"])
    content = str(message["content"])
    return MemoryMessage(
        message_index=int(message["message_index"]),
        role=role,
        content=content,
        scope=scope,
        evidence_eligible=scope == "new" and role == "user" and bool(content.strip()),
    )


def _is_meaningful_user_message(message: dict[str, object]) -> bool:
    return (
        message.get("role") == "user"
        and bool(str(message.get("content") or "").strip())
        and message.get("quality") not in _LOW_INFORMATION_QUALITIES
    )


def _batch_key(conversation_id: str, messages: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    digest.update(conversation_id.encode("utf-8"))
    for message in messages:
        digest.update(str(message["message_index"]).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(message["role"]).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(message["content"]).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()
