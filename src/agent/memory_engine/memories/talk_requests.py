"""Saves how-to-talk requests the moment the request checker finds one, in the turn itself.

Before this, a request ("stop asking that", "english?") held in the same chat through the checker,
and in other chats only once the background run saved it minutes later, if it did. Now the checker
names the requests it read in the user's recent messages, and code saves each as a procedural
memory with that message as evidence. The background run still sees it and may refine or replace it.

A rule is applied to every later reply for good, so one saved from a moment of anger ("do not ask
stupid questions") does harm. The checker judges this well; the background run's long prompt does
not, so a how-to-talk memory that run adds is kept only if the checker also reads a request in its
evidence.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import Any

from agent.context_engine.policy.freshness import _normalize, _word_overlap
from agent.context_engine.policy.requests import request_check_input
from agent.memory_engine.memories.operations import MemoryAddProposal, MemoryAnalysisV3
from agent.memory_engine.processing.models import MemoryBatch
from agent.shared.clock import utc_now
from agent.shared.memory_models import MemoryKind, MemoryPurpose

logger = logging.getLogger(__name__)

EXTRACTOR = "request_check"
# Two requests sharing this much of their words are the same request in other words.
_SAME_REQUEST_OVERLAP = 0.6
_KEY_WORDS = 6


def save_talk_requests(
    user_id: str,
    conversation_id: str,
    history: list[dict[str, Any]],
    user_text: str,
    requests: list[tuple[str, str]],
    *,
    now: datetime | None = None,
) -> list[str]:
    """Create one procedural memory per new request; returns the ids. Never raises."""
    if not requests or not user_id or not conversation_id:
        return []
    try:
        return _save(user_id, conversation_id, history, user_text, requests, now or utc_now())
    except Exception:
        logger.exception("agent.talk_requests.save_failed")
        return []


def _save(user_id: str, conversation_id: str, history: list[dict[str, Any]], user_text: str, requests: list[tuple[str, str]], now: datetime) -> list[str]:
    from storage import create_agent_memory, get_conversation, list_agent_memories

    conversation = get_conversation(conversation_id, user_id)
    if not conversation or conversation.get("temporary"):
        return []
    existing = [
        _normalize(str(memory.get("statement") or memory.get("value") or ""))
        for memory in list_agent_memories(user_id)
        if memory.get("kind") == MemoryKind.PROCEDURAL.value and memory.get("status", "active") == "active"
    ]
    saved: list[str] = []
    for request, source in requests:
        normalized = _normalize(request)
        if not normalized or any(_word_overlap(normalized, other) >= _SAME_REQUEST_OVERLAP for other in existing if other):
            continue
        index = _message_index(history, user_text, source)
        if index is None:
            continue
        memory = create_agent_memory(
            {
                "user_id": user_id,
                "kind": MemoryKind.PROCEDURAL.value,
                "purposes": [MemoryPurpose.PERSONALIZATION.value],
                "key": "how_to_talk." + "_".join(normalized.split()[:_KEY_WORDS]),
                "value": request,
                "statement": request,
                "confidence": 0.8,
                "importance": 0.7,
                "evidence": [{"conversation_id": conversation_id, "message_index": index, "exact_quote": source[:300], "observed_at": now.isoformat()}],
                "extractor": EXTRACTOR,
            }
        )
        existing.append(normalized)
        saved.append(str(memory["id"]))
    return saved


def _message_index(history: list[dict[str, Any]], user_text: str, source: str) -> int | None:
    """Where the quoted user message sits in the stored chat: the current message comes after the history."""
    for index in range(len(history) - 1, -1, -1):
        message = history[index]
        if message.get("role") == "user" and str(message.get("content") or "").strip()[: len(source)] == source:
            return index
    if user_text and user_text.strip()[: len(source)] == source:
        return len(history)
    return None


async def without_unclear_requests(batch: MemoryBatch, analysis: MemoryAnalysisV3) -> MemoryAnalysisV3:
    """Drops how-to-talk memories the background run added when the checker reads no request in
    their evidence. Only additions are checked, so this costs a call only when one is proposed."""
    kept = [
        operation
        for operation in analysis.operations
        if not (isinstance(operation, MemoryAddProposal) and operation.kind == MemoryKind.PROCEDURAL and await _no_request_in_evidence(batch, operation))
    ]
    if len(kept) == len(analysis.operations):
        return analysis
    logger.info("agent.talk_requests.dropped_unclear count=%s", len(analysis.operations) - len(kept))
    return replace(analysis, operations=tuple(kept))


async def _no_request_in_evidence(batch: MemoryBatch, proposal: MemoryAddProposal) -> bool:
    from agent.providers import check_reply_requests

    quotes = [message.content for message in batch.messages if message.message_index in proposal.evidence_message_indexes]
    if not quotes:
        return False
    try:
        raw = await check_reply_requests(request_check_input("", [], quotes, []), conversation_id=batch.conversation_id)
    except Exception as error:
        logger.warning("agent.talk_requests.check_failed error_type=%s", type(error).__name__)
        return False
    return isinstance(raw, dict) and raw.get("requests") == []


__all__ = ["EXTRACTOR", "save_talk_requests", "without_unclear_requests"]
