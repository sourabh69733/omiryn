"""Verifies safe, bounded retrieval of canonical v3 memories for replies."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import storage
from agent.context_engine.assembly.sources import build_reply_context_sources


USER_ID = "memory-v3-retrieval-user"
CONVERSATION_ID = "memory-v3-retrieval-conversation"
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


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


def test_retrieval_excludes_inactive_disallowed_and_highly_sensitive_memories() -> None:
    allowed = _save_memory(key="home.location", value="Pune")
    _save_memory(key="private.health", value="diagnosis", sensitivity="highly_sensitive")
    _save_memory(key="matching.only", value="vegetarian", allowed_uses=["matching"])
    _save_memory(key="old.location", value="Bengaluru", status="superseded")

    selected = _retrieve("Where am I based?")

    assert [memory["id"] for memory in selected] == [allowed["id"]]


def test_retrieval_is_kind_aware_and_ranks_relevant_memory_first() -> None:
    unrelated = _save_memory(
        key="food.preference",
        value="spicy food",
        confidence=1.0,
        importance=1.0,
    )
    relevant = _save_memory(
        key="relationship.riya",
        value={"person": "Riya", "pattern": "feels understood by her"},
        kind="relationship",
        purposes=["personalization"],
        confidence=0.8,
        importance=0.7,
    )
    procedural = _save_memory(
        key="conversation.style",
        value="Do not ask many questions at once",
        kind="procedural",
        purposes=["personalization"],
    )

    selected = _retrieve("Riya called me again")

    ids = [memory["id"] for memory in selected]
    assert ids.index(relevant["id"]) < ids.index(unrelated["id"])
    assert procedural["id"] in ids


def test_retrieval_limits_each_kind_and_total_context() -> None:
    for index in range(4):
        _save_memory(
            key=f"profile.fact.{index}",
            value=f"fact {index}",
            importance=1.0 - index / 10,
        )
    for index in range(3):
        _save_memory(
            key=f"event.{index}",
            value=f"event {index}",
            kind="episodic",
            purposes=["personalization"],
            importance=1.0 - index / 10,
        )

    selected = _retrieve("Tell me what you remember", limit=5)

    assert len(selected) <= 5
    assert sum(item["kind"] == "semantic" for item in selected) == 2
    assert sum(item["kind"] == "episodic" for item in selected) == 1


def test_context_uses_v3_memories_only_for_v3_pipeline() -> None:
    memory = _save_memory(
        key="relationship.riya",
        value={"person": "Riya", "experience": "easy conversations"},
        kind="relationship",
        purposes=["personalization"],
    )

    with patch.dict(os.environ, {"AGENT_PIPELINE_VERSION": "v3"}, clear=False):
        v3_sources = build_reply_context_sources(
            CONVERSATION_ID,
            None,
            "Riya messaged me",
            USER_ID,
        )
    with patch.dict(
        os.environ,
        {"AGENT_PIPELINE_VERSION": "v2", "AGENT_ROLLOUT": "live"},
        clear=False,
    ):
        v2_sources = build_reply_context_sources(
            CONVERSATION_ID,
            None,
            "Riya messaged me",
            USER_ID,
        )

    v3_memory_source = next(
        source for source in v3_sources if source["source_type"] == "agent_memories_v3"
    )
    assert memory["id"] in v3_memory_source["metadata"]["memory_ids"]
    assert "Riya" in v3_memory_source["content"]
    assert all(source["source_type"] != "agent_memories_v3" for source in v2_sources)


def _retrieve(user_text: str, *, limit: int = 5) -> list[dict[str, object]]:
    package = importlib.import_module("agent.memory_engine.memories")
    function = getattr(package, "retrieve_agent_memories_for_reply", None)
    assert callable(function), "v3 reply-memory retrieval is missing"
    return function(USER_ID, user_text, limit=limit, now=NOW)


def _save_memory(
    *,
    key: str,
    value: object,
    kind: str = "semantic",
    purposes: list[str] | None = None,
    allowed_uses: list[str] | None = None,
    sensitivity: str = "standard",
    status: str = "active",
    confidence: float = 0.9,
    importance: float = 0.8,
) -> dict[str, object]:
    observed_at = (NOW - timedelta(days=1)).isoformat()
    return storage.create_agent_memory(
        {
            "user_id": USER_ID,
            "kind": kind,
            "purposes": purposes or ["profile"],
            "key": key,
            "value": value,
            "allowed_uses": allowed_uses or ["reply_context"],
            "status": status,
            "sensitivity": sensitivity,
            "confidence": confidence,
            "importance": importance,
            "evidence": [
                {
                    "conversation_id": CONVERSATION_ID,
                    "message_index": 0,
                    "exact_quote": f"Evidence for {key}",
                    "observed_at": observed_at,
                }
            ],
        }
    )
